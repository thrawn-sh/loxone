import abc
import datetime
import enum
import statistics
import logging
import uuid


class Entity(abc.ABC):
    @abc.abstractmethod
    def getValue(self) -> bool | float:
        pass


class ChangeResponse(enum.Enum):
    IMMEDIATE = 2
    LATER = 1
    NO = 0


class RawValue(Entity):

    def __init__(self, id: str, registry: any, changeResponse: ChangeResponse = ChangeResponse.LATER) -> None:
        self.id = id
        self.value: bool | float = None
        self.changeResponse = changeResponse
        registry.register(id, Callback(id, self))

    def getValue(self) -> bool | float:
        return self.value

    def setValue(self, value: bool | float) -> ChangeResponse:
        if self.value == value:
            return ChangeResponse.NO
        Registry._LOGGER.info(f'setting {self.id} to {value}')
        self.value = value
        return self.changeResponse


class BoolValue(RawValue):
    def __init__(self, id: str, registry: any, changeResponse: ChangeResponse) -> None:
        super().__init__(id, registry, changeResponse)

    def setValue(self, value: float) -> bool:
        if value is None:
            return super().setValue(None)
        else:
            return super().setValue(bool(value))


class RoundedValue(RawValue):
    def __init__(self, id: str, registry: any, changeResponse: ChangeResponse, scale: float = 0.1) -> None:
        super().__init__(id, registry, changeResponse)
        self.scale = scale

    def setValue(self, value: float) -> bool:
        if value is None:
            return super().setValue(None)
        else:
            # round to nearest multiple of scale
            return super().setValue(round(value / self.scale) * self.scale)


class Aggreate(Entity):
    def __init__(self, entities: list[RawValue]) -> None:
        self.entities: list[RawValue] = entities


class OrAggregate(Aggreate):
    def __init__(self, entities: list[BoolValue]) -> None:
        super().__init__(entities)

    def getValue(self) -> bool:
        values = [entity.getValue() for entity in self.entities if entity.getValue() is not None]
        return any(values) if values else None


class AndAggregate(Aggreate):
    def __init__(self, entities: list[BoolValue]) -> None:
        super().__init__(entities)

    def getValue(self) -> bool:
        values = [entity.getValue() for entity in self.entities if entity.getValue() is not None]
        return all(values) if values else None


class MeanAggregate(Aggreate):
    def __init__(self, entities: list[RoundedValue]) -> None:
        super().__init__(entities)

    def getValue(self) -> float:
        values = [entity.getValue() for entity in self.entities if entity.getValue() is not None]
        return statistics.mean(values) if values else None


class MedianAggregate(Aggreate):
    def __init__(self, entities: list[RoundedValue]) -> None:
        super().__init__(entities)

    def getValue(self) -> float:
        values = [entity.getValue() for entity in self.entities if entity.getValue() is not None]
        return statistics.median(values) if values else None


class Callback():
    def __init__(self, id: str, entity: RawValue) -> None:
        self.id = id
        self.entity = entity

    def update(self, value: float) -> ChangeResponse:
        return self.entity.setValue(value)


class Registry(abc.ABC):

    _LOGGER = logging.getLogger('loxone.model.Registry')

    @staticmethod
    def _buildTyping(structureFile: object) -> dict[str, str]:
        typing: dict[str, str] = {
        }
        for globalState, id in structureFile['globalStates'].items():
            Registry._LOGGER.debug(f'found {id}: globalState -> {globalState}')
            typing[id] = f'globalState -> {globalState}'
        for _, control in structureFile['controls'].items():
            type = control.get('type')
            room = structureFile['rooms'][control.get('room')]['name']
            states = control.get('states')
            if states is not None:
                for state, id in states.items():
                    Registry._LOGGER.debug(f'found {id}: {type} ({room}) -> {state}')
                    typing[id] = f'{type} ({room}) -> {state}'

            subControls = control.get('subControls')
            if subControls is not None:
                for _, subcontrol in subControls.items():
                    subtype = subcontrol.get('type')
                    states = subcontrol.get('states')
                    if states is not None:
                        for state, id in states.items():
                            Registry._LOGGER.debug(f'SUB found {id}: {type}->{subtype} ({room}) -> {state}')
                            typing[id] = f'{type}->{subtype} ({room}) -> {state}'
        return typing

    def __init__(self, structureFile: object) -> None:
        self.registry: dict[str, Callback] = {}
        self.typing = Registry._buildTyping(structureFile)

    def register(self, id: str, function: Callback) -> None:
        if id in self.registry:
            raise ValueError(f'ID {id} already registered')
        self.registry[id] = function

    def update(self, id: str, value: float) -> ChangeResponse:
        if id in self.registry:
            self._LOGGER.debug(f'updating {id} to {value} ({self.typing[id]})')
            return self.registry[id].update(value)
        else:
            self._LOGGER.debug(f'unregistered {id} to {value} ({self.typing.get(id, "unknown")})')
            return ChangeResponse.NO


class Building(Registry):

    def __init__(self, structureFile: object) -> None:
        super().__init__(structureFile)
        self.name: str = structureFile['msInfo']['msName']
        self.serial: str = structureFile['msInfo']['serialNr']
        self.lastModified: datetime = datetime.datetime.fromisoformat(structureFile['lastModified'])
        self.rooms: list[Room] = [Room(room, structureFile, self) for _, room in structureFile['rooms'].items()]
        self.change = ChangeResponse.NO
        self.lastPersisted = 0


class Room:
    def __init__(self, room: object, structureFile: object, registry: Registry) -> None:
        self.id: uuid.UUID = uuid.UUID(room['uuid'])
        self.name: str = room['name']

        controls = [control for _, control in structureFile['controls'].items() if control.get('room') == room['uuid']]
        heatingControls = [
            hc for hc in controls if hc.get('type') == 'IRoomControllerV2'
        ]
        lightsControls = [
            lc for lc in controls if lc.get('type') == 'LightControllerV2'
        ]
        switchControls = [
            sc for lc in lightsControls for _, sc in lc.get('subControls', {}).items() if sc.get('type') == 'Switch'
        ]
        precenceControls = [
            pc for pc in controls if pc.get('type') == 'PresenceDetector'
        ]
        shadesControls = [
            sc for sc in controls if sc.get('type') == 'Jalousie'
        ]

        self.temperature: Entity = MeanAggregate([RoundedValue(hc['states']['tempActual'], registry, ChangeResponse.LATER, 0.5) for hc in heatingControls])
        self.temperatureTarget: Entity = MeanAggregate([RoundedValue(hc['states']['tempTarget'], registry, ChangeResponse.LATER, 0.5) for hc in heatingControls])
        self.humidity: Entity = MeanAggregate([RoundedValue(hc['states']['humidityActual'], registry, ChangeResponse.LATER, 0.5) for hc in heatingControls])
        self.light: Entity = OrAggregate([BoolValue(sc['states']['active'], registry, ChangeResponse.IMMEDIATE) for sc in switchControls])
        self.shading: Entity = MeanAggregate([RoundedValue(sc['states']['position'], registry, ChangeResponse.LATER, 1) for sc in shadesControls])
        self.valve: Entity = MeanAggregate([])
        self.ventilation: Entity = OrAggregate([BoolValue(hc['states']['openWindow'], registry, ChangeResponse.LATER) for hc in heatingControls])
        self.precence: Entity = OrAggregate([BoolValue(pc['states']['active'], registry, ChangeResponse.IMMEDIATE) for pc in precenceControls])
