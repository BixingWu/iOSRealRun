from iosrealrun.config import Config
from iosrealrun.desktop_routes import load_route


def get_route():
    points, _ = load_route(Config().routeConfig)
    return points
