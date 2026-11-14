"""
run.py
automatically run the route
"""

"""修正坐标误差，百度取点使用 BD-09 坐标系，iOS使用 WGS-09 坐标系，进行转换"""
import math
import time
import random
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from geopy.distance import geodesic

from pymobiledevice3.dtx.exceptions import DTXNsError, DTXProtocolError
from pymobiledevice3.exceptions import PyMobileDevice3Exception
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.simulate_location import DtSimulateLocation

def bd09Towgs84(position):
    wgs_p = {}

    x_pi = 3.14159265358979324 * 3000.0 / 180.0
    pi = 3.141592653589793238462643383  # π
    a = 6378245.0  # 长半轴
    ee = 0.00669342162296594323  # 偏心率平方

    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * pi) + 40.0 * math.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * pi) + 320 * math.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lon(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * pi) + 40.0 * math.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * pi) + 300.0 * math.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret

    x = position['lng'] - 0.0065
    y = position['lat'] - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)

    gcj_lng = z * math.cos(theta)
    gcj_lat = z * math.sin(theta)

    d_lat = transform_lat(gcj_lng - 105.0, gcj_lat - 35.0)
    d_lng = transform_lon(gcj_lng - 105.0, gcj_lat - 35.0)

    rad_lat = gcj_lat / 180.0 * pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)

    d_lng = (d_lng * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * pi)
    d_lat = (d_lat * 180.0) / (a * (1 - ee) / (magic * sqrt_magic) * pi)

    wgs_p["lat"] = gcj_lat * 2 - gcj_lat - d_lat
    wgs_p["lng"] = gcj_lng * 2 - gcj_lng - d_lng
    return wgs_p


def _gcj02_to_wgs84(gcj_lat, gcj_lng):
    """Convert a GCJ-02 coordinate to WGS84."""
    pi = math.pi
    a = 6378245.0
    ee = 0.00669342162296594323

    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * pi) + 40.0 * math.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * pi) + 320 * math.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lon(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * pi) + 40.0 * math.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * pi) + 300.0 * math.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret

    d_lat = transform_lat(gcj_lng - 105.0, gcj_lat - 35.0)
    d_lng = transform_lon(gcj_lng - 105.0, gcj_lat - 35.0)
    rad_lat = gcj_lat / 180.0 * pi
    magic = 1 - ee * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lng = d_lng * 180.0 / (a / sqrt_magic * math.cos(rad_lat) * pi)
    d_lat = d_lat * 180.0 / (a * (1 - ee) / (magic * sqrt_magic) * pi)
    return {"lat": gcj_lat - d_lat, "lng": gcj_lng - d_lng}


def to_wgs84(position, coordinate_system="bd09"):
    system = coordinate_system.lower().replace("-", "")
    if system == "bd09":
        return bd09Towgs84(position)
    if system == "gcj02":
        return _gcj02_to_wgs84(position["lat"], position["lng"])
    if system == "wgs84":
        return {"lat": position["lat"], "lng": position["lng"]}
    raise ValueError(f"Unsupported coordinate system: {coordinate_system}")

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
        print("跑完一圈了")

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
