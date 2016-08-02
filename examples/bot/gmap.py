class Map(object):
    def __init__(self):
        self._points = []
        self._positions = []
        self._bounds = []
        self._player = None
    def add_point(self, coordinates, color="#FF0000"):
        self._points.append((coordinates, color))
    def add_position(self, coordinates):
        self._positions.append(coordinates)
    def add_bound(self, coordinates):
        self._bounds.append(coordinates)
    def __str__(self):
        return("raw = '[%s]';" % json.dumps({"points" : self._points, "positions" : self._positions, "bounds" : self._bounds, "player" : self._player}))
