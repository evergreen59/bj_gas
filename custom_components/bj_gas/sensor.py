from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import (
    STATE_UNKNOWN,
    UnitOfVolume,
    UnitOfElectricPotential,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from .const import DOMAIN

GAS_SENSORS = {
    "balance": {
        "name": "燃气费余额",
        "icon": "hass:cash-100",
        "unit_of_measurement": "元",
        "attributes": ["last_update"]
    },
    "current_level": {
        "name": "当前燃气阶梯",
        "icon": "hass:stairs",
    },
    "current_price": {
        "name": "当前气价",
        "icon": "hass:cash-100",
        "unit_of_measurement": "元/m³",
    },
    "current_level_remain": {
        "name": "当前阶梯剩余额度",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
    },
    "year_consume": {
        "name": "本年度用气量",
        "device_class": SensorDeviceClass.GAS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
    },
    "month_reg_qty": {
        "name": "当月用气量",
        "device_class": SensorDeviceClass.GAS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
    },
    "battery_voltage": {
        "name": "气表电量",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
    },
    "mtr_status": {
        "name": "阀门状态",
        # Although there is no direct device class for valve status,
        # using GAS is acceptable as it's related.
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": "",
    }
}


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the sensor platform."""
    sensors = []
    coordinator = hass.data[DOMAIN]
    for user_code, data in coordinator.data.items():
        for key in GAS_SENSORS.keys():
            if key in data.keys():
                sensors.append(GASSensor(coordinator, user_code, key))
        if "monthly_bills" in data:
            for month in range(len(data["monthly_bills"])):
                sensors.append(GASHistorySensor(coordinator, user_code, month))
        if "daily_bills" in data:
            for day in range(len(data["daily_bills"])):
                sensors.append(GASDailyBillSensor(coordinator, user_code, day))
    async_add_devices(sensors, True)


class GASBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for BJ Gas sensors."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._unique_id = None

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def should_poll(self):
        """No need to poll. Coordinator provides updates."""
        return False


class GASSensor(GASBaseSensor):
    """Representation of a BJ Gas sensor."""

    def __init__(self, coordinator, user_code, sensor_key):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._user_code = user_code
        self._sensor_key = sensor_key
        self._config = GAS_SENSORS[self._sensor_key]
        self._attributes = self._config.get("attributes")
        self._coordinator = coordinator
        self._unique_id = f"{DOMAIN}.gas_{user_code}_{sensor_key}"
        self.entity_id = self._unique_id

    def get_value(self, attribute=None):
        """Get the value of the sensor."""
        try:
            if attribute is None:
                return self._coordinator.data.get(self._user_code).get(self._sensor_key)
            return self._coordinator.data.get(self._user_code).get(attribute)
        except (KeyError, AttributeError):
            return STATE_UNKNOWN

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._config.get("name")

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.get_value()

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return self._config.get("icon")

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return self._config.get("device_class")

    @property
    def state_class(self):
        """Return the state class of the sensor."""
        return self._config.get("state_class")

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._config.get("unit_of_measurement")

    @property
    def extra_state_attributes(self):
        """Return the extra state attributes."""
        attributes = {}
        if self._attributes is not None:
            try:
                for attribute in self._attributes:
                    attributes[attribute] = self.get_value(attribute)
            except (KeyError, AttributeError):
                pass
        return attributes


class GASHistorySensor(GASBaseSensor):
    """Representation of a BJ Gas monthly history sensor."""

    def __init__(self, coordinator, user_code, index):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._user_code = user_code
        self._coordinator = coordinator
        self._index = index
        self._unique_id = f"{DOMAIN}.gas_{user_code}_monthly_{index + 1}"
        self.entity_id = self._unique_id

    @property
    def name(self):
        """Return the name of the sensor."""
        try:
            return '燃气消耗 ' + self._coordinator.data.get(self._user_code).get("monthly_bills")[self._index].get("mon")
        except (KeyError, AttributeError, IndexError, TypeError):
            return STATE_UNKNOWN

    @property
    def state(self):
        """Return the state of the sensor."""
        try:
            return self._coordinator.data.get(self._user_code).get("monthly_bills")[self._index].get("regQty")
        except (KeyError, AttributeError, IndexError, TypeError):
            return STATE_UNKNOWN

    @property
    def extra_state_attributes(self):
        """Return the extra state attributes."""
        try:
            return {
                "consume_bill": self._coordinator.data.get(self._user_code).get("monthly_bills")[self._index].get(
                    "amt")
            }
        except (KeyError, AttributeError, IndexError, TypeError):
            return {"consume_bill": 0.0}

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return SensorDeviceClass.GAS

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return UnitOfVolume.CUBIC_METERS


class GASDailyBillSensor(GASBaseSensor):
    """Representation of a BJ Gas daily bill sensor."""

    def __init__(self, coordinator, user_code, index):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._user_code = user_code
        self._coordinator = coordinator
        self._index = index
        self._unique_id = f"{DOMAIN}.gas_{user_code}_daily_{index + 1}"
        self.entity_id = self._unique_id

    @property
    def name(self):
        """Return the name of the sensor."""
        try:
            return '燃气消耗 ' + self._coordinator.data.get(self._user_code).get("daily_bills")[self._index].get("day")[:10]
        except (KeyError, AttributeError, IndexError, TypeError):
            return STATE_UNKNOWN

    @property
    def state(self):
        """Return the state of the sensor."""
        try:
            return self._coordinator.data.get(self._user_code).get("daily_bills")[self._index].get("regQty")
        except (KeyError, AttributeError, IndexError, TypeError):
            return STATE_UNKNOWN

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return SensorDeviceClass.GAS

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return UnitOfVolume.CUBIC_METERS
