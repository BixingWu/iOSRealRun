"""
run.py
automatically run the route
"""

import math
import time
import random
import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from geopy.distance import geodesic

from pymobiledevice3.dtx.exceptions import DTXNsError, DTXProtocolError
from pymobiledevice3.exceptions import PyMobileDevice3Exception
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.simulate_location import DtSimulateLocation

from iosrealrun.coordinates import _gcj02_to_wgs84, bd09Towgs84, to_wgs84

logger = logging.getLogger(__name__)

# get the ditance according to the latitude and longitude
def geodistance(p1, p2):
    return geodesic((p1["lat"],p1["lng"]),(p2["lat"],p2["lng"])).m

def smooth(start, end, i):
    import math
    i = (i-start)/(end-start)*math.pi
    return math.sin(i)**2

def randLoc(loc: list, d=0.000025, n=5):
    import random
    import time
    import math
    # deepcopy loc
    result = []
    for i in loc:
        result.append(i.copy())

    center = {"lat": 0, "lng": 0}
    for i in result:
        center["lat"] += i["lat"]
        center["lng"] += i["lng"]
    center["lat"] /= len(result)
    center["lng"] /= len(result)
    random.seed(time.time())
    for i in range(n):
        start = int(i*len(result)/n)
        end = int((i+1)*len(result)/n)
        offset = (2*random.random()-1) * d
        for j in range(start, end):
            distance = math.sqrt(
                (result[j]["lat"]-center["lat"])**2 + (result[j]["lng"]-center["lng"])**2
            )
            if 0 == distance:
                continue
            result[j]["lat"] +=  (result[j]["lat"]-center["lat"])/distance*offset*smooth(start, end, j)
            result[j]["lng"] +=  (result[j]["lng"]-center["lng"])/distance*offset*smooth(start, end, j)
    start = int(i*len(result)/n)
    end = len(result)
    offset = (2*random.random()-1) * d
    for j in range(start, end):
        distance = math.sqrt(
            (result[j]["lat"]-center["lat"])**2 + (result[j]["lng"]-center["lng"])**2
        )
        if 0 == distance:
            continue
        result[j]["lat"] +=  (result[j]["lat"]-center["lat"])/distance*offset*smooth(start, end, j)
        result[j]["lng"] +=  (result[j]["lng"]-center["lng"])/distance*offset*smooth(start, end, j)
    return result

def fixLockT(loc: list, v, dt):
    fixedLoc = []
    t = 0
    T = []
    T.append(geodistance(loc[1],loc[0])/v)
    a = loc[0].copy()
    b = loc[1].copy()
    j = 0
    while t < T[0]:
        xa = a["lat"] + j*(b["lat"]-a["lat"])/(max(1, int(T[0]/dt)))
        xb = a["lng"] + j*(b["lng"]-a["lng"])/(max(1, int(T[0]/dt)))
        fixedLoc.append({"lat": xa, "lng": xb})
        j += 1
        t += dt
    for i in range(1, len(loc)):
        T.append(geodistance(loc[(i+1)%len(loc)],loc[i])/v + T[-1])
        a = loc[i].copy()
        b = loc[(i+1)%len(loc)].copy()
        j = 0
        while t < T[i]:
            xa = a["lat"] + j*(b["lat"]-a["lat"])/(max(1, int((T[i]-T[i-1])/dt)))
            xb = a["lng"] + j*(b["lng"]-a["lng"])/(max(1, int((T[i]-T[i-1])/dt)))
            fixedLoc.append({"lat": xa, "lng": xb})
            j += 1
            t += dt
    return fixedLoc

async def run1(location_simulation, loc: list, v, dt=0.2,
               coordinate_system="bd09", stop_requested=None):
    fixedLoc = fixLockT(loc, v, dt)
    nList = (5, 6, 7, 8, 9)
    n = nList[random.randint(0, len(nList)-1)]
    fixedLoc = randLoc(fixedLoc, n=n)  # a path will be divided into n parts for random route
    clock = time.time()
    for i in fixedLoc:
        if stop_requested is not None and stop_requested():
            return False
        wgs = to_wgs84(i, coordinate_system)
        await location_simulation.set(wgs["lat"], wgs["lng"])
        await asyncio.sleep(max(0, dt - (time.time() - clock)))
        clock = time.time()
    return True

def _should_continue(loop_count, loop_index, stop_requested):
    if stop_requested is not None and stop_requested():
        return False
    return not loop_count or loop_index < loop_count

async def _run_with_location_simulation(location_simulation, loc: list, v, d=15,
                                        loop_count=0, stop_requested=None,
                                        update_interval=0.2,
                                        coordinate_system="bd09"):
    loop_index = 0
    while _should_continue(loop_count, loop_index, stop_requested):
        loop_index += 1
        pace_factor = max(0.5, 1 - (2 * random.random() - 1) * d * (v / 1000))
        vRand = v / pace_factor
        completed = await run1(
            location_simulation, loc, vRand, dt=update_interval,
            coordinate_system=coordinate_system,
            stop_requested=stop_requested
        )
        if not completed:
            break
        logger.info("已完成第 %d 圈。", loop_index)

@asynccontextmanager
async def dvt_location(rsd):
    dvt = DvtProvider(rsd)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(dvt.close)
        # v11.54.0 handles its own 15-second handshake timeout, yet leaves a
        # partial DTX connection open if its connect coroutine is cancelled.
        connecting = asyncio.create_task(dvt.connect())
        try:
            await asyncio.shield(connecting)
        except asyncio.CancelledError:
            with suppress(PyMobileDevice3Exception, OSError, EOFError, DTXNsError, DTXProtocolError):
                await connecting
            raise
        location = await asyncio.wait_for(stack.enter_async_context(LocationSimulation(dvt)), 8)
        yield location


async def run(address, port, loc: list, v, d=15, loop_count=0,
              stop_requested=None, clear_on_finish=False,
              update_interval=0.2, coordinate_system="bd09"):
    random.seed(time.time())
    rsd = RemoteServiceDiscoveryService((address, port))
    try:
        await asyncio.wait_for(rsd.connect(), 20)
        async with dvt_location(rsd) as location_simulation:
            try:
                await _run_with_location_simulation(
                    location_simulation, loc, v, d, loop_count, stop_requested,
                    update_interval, coordinate_system
                )
            finally:
                if clear_on_finish:
                    await _restore_location(location_simulation)
    finally:
        await rsd.close()

async def run_legacy(loc: list, v, d=15, loop_count=0,
                     stop_requested=None, clear_on_finish=False,
                     update_interval=0.2, coordinate_system="bd09", *, serial=None):
    random.seed(time.time())
    async with await create_using_usbmux(serial=serial, connection_type="USB", autopair=False) as lockdown:
        location_simulation = DtSimulateLocation(lockdown)
        try:
            await _run_with_location_simulation(
                location_simulation, loc, v, d, loop_count, stop_requested,
                update_interval, coordinate_system
            )
        finally:
            if clear_on_finish:
                await _restore_location(location_simulation)


async def _restore_location(location_simulation):
    try:
        await asyncio.wait_for(location_simulation.clear(), 8)
    except Exception as error:
        raise RuntimeError(f"未能恢复设备定位。重新连接设备后请重试恢复定位。{error}") from error
