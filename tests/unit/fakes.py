class FakeDriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate
