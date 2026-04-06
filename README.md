# Librus Synergia - Home Assistant Integration

Custom Home Assistant integration for [Librus Synergia](https://synergia.librus.pl/) - Polish school management system.

## Features

- **Automatic authentication** via Librus OAuth (parent portal login)
- **Dynamic per-subject grade sensors** - automatically creates sensors for each subject
- **New grade notifications** - persistent notifications + `librus_new_grade` event for automations
- **Auto-semester detection** - switches between semester 1 and 2 based on school calendar
- **Lucky number** sensor
- **Configurable scan interval** (5-120 minutes, default: 15)
- **Multiple accounts** - add separate entries for each child
- **Reauth flow** - easily update password when it changes

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Librus Synergia" and install
3. Restart Home Assistant
4. Go to Settings > Integrations > Add Integration > Librus Synergia

### Manual

1. Copy `custom_components/ha_librus` folder to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings > Integrations > Add Integration > Librus Synergia

## Configuration

Enter your Librus Synergia parent login credentials:
- **Login** - your numeric login (e.g., 1234567)
- **Password** - your Librus password
- **Scan interval** - how often to check for new grades (default: 15 minutes)

## Sensors

Entity IDs contain the Librus student login ID (e.g. `1234567`) to avoid collisions when multiple children are configured.

### Static sensors (always present)
| Sensor | Description |
|--------|-------------|
| `sensor.librus_1234567_uczen` | Student name, class, semester |
| `sensor.librus_1234567_oceny_wszystkie` | All grades summary |
| `sensor.librus_1234567_ostatnia_ocena` | Most recent grade with details |
| `sensor.librus_1234567_szczesliwy_numerek` | Today's lucky number |

### Dynamic sensors (per subject)
For each subject with grades, a sensor is automatically created:
- `sensor.librus_1234567_biologia`
- `sensor.librus_1234567_matematyka`
- `sensor.librus_1234567_jezyk_polski`
- etc.

Each subject sensor includes attributes: `ostatnia_ocena`, `data_ostatniej`, `kategoria`, `liczba_ocen`.

## Automations

Use the `librus_new_grade` event to trigger automations:

```yaml
automation:
  - alias: "Notify on new Librus grade"
    trigger:
      - platform: event
        event_type: librus_new_grade
    action:
      - service: notify.notify
        data:
          title: "{{ trigger.event.data.title }}"
          message: "{{ trigger.event.data.message }}"
```

## Troubleshooting

- **Authentication fails**: Make sure you use the parent portal login (numeric), not the student login
- **No grades showing**: Check if the school year is active and grades exist for the current semester
- **Token errors**: The integration handles token refresh automatically (every 8 minutes)

## Credits

Built for Home Assistant using Librus Synergia API.
