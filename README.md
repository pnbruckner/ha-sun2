# <img src="https://brands.home-assistant.io/sun2/icon.png" alt="Sun2 Sensor" width="50" height="50"/> Sun2 Sensor

Creates sensors that provide information about various sun related events.

Follow the installation instructions below.
Then add one or more locations with desired sensors either via YAML, the UI or both.

## Installation
### With HACS
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

You can use HACS to manage the installation and provide update notifications.

1. Add this repo as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/):

```text
https://github.com/pnbruckner/ha-sun2
```

2. Install the integration using the appropriate button on the HACS Integrations page. Search for "sun2".

### Manual

Place a copy of the files from [`custom_components/sun2`](custom_components/sun2)
in `<config>/custom_components/sun2`,
where `<config>` is your Home Assistant configuration directory.

>__NOTE__: When downloading, make sure to use the `Raw` button from each file's page.

### Versions

This custom integration supports HomeAssistant versions 2023.4.0 or newer.

## Services

### `sun2.reload`

Reloads Sun2 from the YAML-configuration. Also adds `SUN2` to the Developers Tools -> YAML page.

## Configuration variables

A list of configuration options for one or more "locations". Each location is defined by the following options.

> Note: This defines configuration via YAML. However, the same sensors can be added to locations created in the UI.

Key | Optional | Description
-|-|-
`unique_id` | no | Unique identifier for location. This allows any of the remaining options to be changed without looking like a new location.
`location` | yes* | Name of location
`latitude` | yes* | The location's latitude (in degrees)
`longitude` | yes* | The location's longitude (in degrees)
`time_zone` | yes* | The location's time zone. (See the "TZ database name" column at http://en.wikipedia.org/wiki/List_of_tz_database_time_zones.)
`elevation` | yes* | The observer's elevation above ground level at specified location (in meters)
`binary_sensors` | yes | Binary sensor configurations as defined [here](#binary-sensor-configurations)
`sensors` | yes | Sensor configurations as defined [here](#sensor-configurations)

\* These must all be used together. If not used, the default is Home Assistant's location, elevation & name configuration.

> NOTE: Home Assistant describes the elevation setting as "above sea level."
> For the purpose of determining sunrise, etc., that is incorrect.
> It should be the observer's elevation above ground level at the specified location.
> For more details, see [Effect of Elevation](https://sffjunkie.github.io/astral/#effect-of-elevation)

### Binary Sensor Configurations

A list of one or more of the following.

#### `elevation`

`'on'` when sun's elevation is above threshold, `'off'` when at or below threshold.

Key | Optional | Description
-|-|-
`unique_id` | no | Unique identifier for entity. Must be unique within set of binary sensors for location. This allows any of the remaining options to be changed without looking like a new entity.
`elevation` | no | Elevation threshold (in degrees) or `horizon`
`name` | yes | Entity friendly name

For example, this:

```yaml
- unique_id: bs1
  elevation: horizon
```

Would be equivalent to:

```yaml
- unique_id: bs1
  elevation: -0.833
  name: Above horizon
```

### Sensor Configurations

A list of one or more of the following.

#### Time at Elevation Sensor

Key | Optional | Description
-|-|-
`unique_id` | no | Unique identifier for entity. Must be unique within set of sensors for location. This allows any of the remaining options to be changed without looking like a new entity.
`time_at_elevation` | no | Elevation (in degrees)
`direction` | yes | `rising` (default) or `setting`
`icon` | yes | Default is `mdi:weather-sunny`
`name` | yes | Entity friendly name

For example, this:

```yaml
- unique_id: s1
  time_at_elevation: -0.833
```

Would be equivalent to:

```yaml
- unique_id: s1
  time_at_elevation: -0.833
  direction: rising
  icon: mdi:weather-sunny
  name: Rising at minus 0.833 °
```

#### Elevation at Time Sensor

Key | Optional | Description
-|-|-
`unique_id` | no | Unique identifier for entity. Must be unique within set of sensors for location. This allows any of the remaining options to be changed without looking like a new entity.
`elevation_at_time` | no | Time string or `input_datetime` entity ID
`name` | yes | Entity friendly name

When using an `input_datetime` entity it must have the time component. The date component is optional.
If the date is not present, the result will be the sun's elevation at the given time on the current date.
If the date is present, it will be used and the result will be the sun's elevation at the given time on the given date.
Also in this case, the `sensor` entity will not have `yesterday`, `today` and `tomorrow` attributes.

## Aditional Sensors

Besides the sensors described above, the following will also be created automatically. Simply enable or disable these entities as desired.

### Point in Time Sensors

Some of these will be enabled by default. The rest will be disabled by default.

Type | Enabled | Description
-|-|-
Solar Midnight | yes | The time when the sun is at its lowest point closest to 00:00:00 of the specified date; i.e. it may be a time that is on the previous day.
Astronomical Dawn | no | The time in the morning when the sun is 18 degrees below the horizon
Nautical Dawn | no | The time in the morning when the sun is 12 degrees below the horizon
Dawn | yes | The time in the morning when the sun is 6 degrees below the horizon
Rising | yes | The time in the morning when the sun is 0.833 degrees below the horizon. This is to account for refraction.
Solar Noon | yes | The time when the sun is at its highest point
Setting | yes | The time in the evening when the sun is 0.833 degrees below the horizon. This is to account for refraction.
Dusk | yes | The time in the evening when the sun is a 6 degrees below the horizon
Nautical Dusk | no | The time in the evening when the sun is a 12 degrees below the horizon
Astronomical Dusk | no | The time in the evening when the sun is a 18 degrees below the horizon

### Length of Time Sensors (in hours)

These are all disabled by default.

Type | Description
-|-
Daylight | The amount of time between sunrise and sunset
Civil Daylight | The amount of time between dawn and dusk
Nautical Daylight | The amount of time between nautical dawn and nautical dusk
Astronomical Daylight | The amount of time between astronomical dawn and astronomical dusk
Night | The amount of time between sunset and sunrise of the next day
Civil Night | The amount of time between dusk and dawn of the next day
Nautical Night | The amount of time between nautical dusk and nautical dawn of the next day
Astronomical Night | The amount of time between astronomical dusk and astronomical dawn of the next day

### Other Sensors

These are also all disabled by default.

Type | Description
-|-
Azimuth | The sun's azimuth (degrees)
Elevation | The sun's elevation (degrees)
Minimum Elevation | The sun's elevation at solar midnight (degrees)
maximum Elevation | The sun's elevation at solar noon (degrees)
deCONZ Daylight | Emulation of [deCONZ Daylight Sensor](https://www.home-assistant.io/integrations/deconz/#deconz-daylight-sensor)
Phase | See [Sun Phase Sensor](#sun-phase-sensor)

##### Sun Phase Sensor

###### Possible states

State | Description
-|-
Night | Sun is below -18°
Astronomical Twilight | Sun is between -18° and -12°
Nautical Twilight | Sun is between -12° and -6°
Civil Twilight | Sun is between -6° and -0.833°
Day | Sun is above -0.833°

###### Attributes

Attribute | Description
-|-
`rising` | `True` if sun is rising
`blue_hour` | `True` if sun is between -6° and -4°
`golden_hour` | `True` if sun is between -4° and 6°

## Example Full Configuration

```yaml
sun2:
  - unique_id: home
    binary_sensors:
      - unique_id: bs1
        elevation: horizon
      - unique_id: bs2
        elevation: 3
      - unique_id: bs3
        elevation: -6
        name: Above Civil Dawn
    sensors:
      - unique_id: s1
        time_at_elevation: 10
      - unique_id: s2
        time_at_elevation: -10
        direction: setting
        icon: mdi:weather-sunset-down
        name: Setting past 10 deg below horizon
      - unique_id: s3
        elevation_at_time: '12:00'
        name: Elv @ noon
      - unique_id: s4
        elevation_at_time: input_datetime.test
        name: Elv @ test var

  - unique_id: london
    location: London
    latitude: 51.50739529645933
    longitude: -0.12767666584664272
    time_zone: Europe/London
    elevation: 0
    binary_sensors:
      - unique_id: bs1
        elevation
      - unique_id: bs2
        elevation: 3
      - unique_id: bs3
        elevation: -6
        name: Above Civil Dawn
    sensors:
      - unique_id: s1
        time_at_elevation: 10
      - unique_id: s2
        time_at_elevation: -10
        direction: setting
        icon: mdi:weather-sunset-down
        name: Setting past 10 deg below horizon
      - unique_id: s3
        elevation_at_time: '12:00'
        name: Elv @ noon
      - unique_id: s4
        elevation_at_time: input_datetime.test
        name: Elv @ test var
```

## Converting from `platform` configuration

In previous versions, configuration was done under `binary_sensor` & `sensor`.
This is now deprecated and will generate a warning at startup.
It should be converted to the new `sun2` format as described above.

Here is an example of the old format:

```yaml
binary_sensor:
  - platform: sun2
    entity_namespace: London
    latitude: 51.50739529645933
    longitude: -0.12767666584664272
    time_zone: Europe/London
    elevation: 0
    monitored_conditions:
      - elevation:
          above: -6
          name: Above Civil Dawn
sensor:
  - platform: sun2
    monitored_conditions:
      - dawn
      - sunrise
      - sunset
      - dusk
      - elevation_at_time: input_datetime.arrival
        name: Elv @ arrival
      - time_at_elevation: -10
        direction: setting
        icon: mdi:weather-sunset-down
        name: Setting past 10 deg below horizon
```

This is the equivalent configuration in the new format:

```yaml
sun2:
  - unique_id: london
    location: London
    latitude: 51.50739529645933
    longitude: -0.12767666584664272
    time_zone: Europe/London
    elevation: 0
    binary_sensors:
      - unique_id: bs1
        elevation: -6
        name: Above Civil Dawn
  - unique_id: home
    sensors:
      - unique_id: s1
        elevation_at_time: input_datetime.arrival
        name: Elv @ arrival
      - unique_id: s2
        time_at_elevation: -10
        direction: setting
        icon: mdi:weather-sunset-down
        name: Setting past 10 deg below horizon
```
All "simple" sensor options (e.g., `sunrise`, `sunset`, etc.) will be created automatically.
Some will be enabled by default, but most will not.
Simply go to the Settings -> Devices & services page, click on Sun2, then entities, and enable/disable the entities as desired.
