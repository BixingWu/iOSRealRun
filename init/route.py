from config import Config
from desktop_routes import load_route


def get_route():
    points, _ = load_route(Config().routeConfig)
    return points
