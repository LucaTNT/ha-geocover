# Decathlon Geocover for Home Assistant

Unofficial Home Assistant integration for Decathlon e-bikes with a Geocover GPS module (Conneqtech
platform), for example the Elops 920E. It shows the same data as the Decathlon Geocover app
(Android `com.conneqtech.decathlon`): position, battery, range, odometer, tracker health and your
latest ride.

It uses [pygeocover](https://github.com/3615nulsi/pygeocover) to talk to the API. **It is read-only:**
no lock or alarm commands are available.

## Installation

### HACS

1. In HACS, open the menu (⋮) → **Custom repositories**, add `https://github.com/lucatnt/ha-geocover`
   with type **Integration**.
2. Install **Decathlon Geocover** and restart Home Assistant.

### Manual

Copy `custom_components/geocover` into your Home Assistant `config/custom_components/` folder and
restart.

## Setup: the login workaround

Go to **Settings → Devices & services → Add integration → Decathlon Geocover**.

The Geocover app logs in with OAuth and only accepts a redirect back into the app
(`tech.conneq.decathlon://…`), which a desktop browser can't open. The integration therefore sends the
login through Decathlon's own login page and lets it end on a page that fails on purpose. Its address
carries the one-time login code, and you paste it into Home Assistant:

1. Open the **Decathlon login page** link shown in the dialog and log in with your Decathlon account
   (the one you use in the Geocover app).
2. You end up on a Conneqtech page saying **"Whoops! Looks like something went wrong"**. That's
   expected: the login worked.
3. **Click in the address bar** and copy the full address. It looks like
   `https://login.ids.conneq.tech/redirect?code=…&state=…`. Safari and some other browsers only show
   part of the address until you click into the bar; if what you copied ends at `/redirect`, it's
   incomplete.
4. Select **Submit** and paste the address in the next step. The code expires after a few minutes. If
   it's rejected, open the login link again and paste the new address.

The `state` part of the address ties it to this login attempt, so an address from an older attempt is
refused.

If Geocover later rejects the stored login, Home Assistant asks you to **re-authenticate**, using the
same two steps.

## Entities

One device per bike on the account. Bikes added to the account later appear automatically.

| Entity | Notes |
|---|---|
| Device tracker | Last GPS position. Attributes: `speed`, `fix_time` |
| Battery | Bike battery % |
| Range | km |
| Odometer | km, total increasing |
| Speed | Speed at the last GPS fix, km/h |
| Tracker battery | Battery of the GPS module itself (diagnostic) |
| Last GPS fix, Last connection | Timestamps (diagnostic) |
| Last ride distance, duration, average speed, elevation gain | Duration is total elapsed time, not moving time. Attributes: `start_time`, `end_time` |
| Last ride CO₂ saved | CO₂ saved versus driving, in kg (the API reports grams) |
| Moving, Ride in progress, Stolen, Charging, Power | Binary sensors |
| ECU lock | Lock binary sensor: **on means unlocked** (Home Assistant convention) |

### Options

**Polling interval:** 5 minutes by default, 1 minute minimum. The latest ride is fetched every 30
minutes, and straight away when a ride ends.

## Limitations

- **Unofficial API.** Decathlon or Conneqtech can change it, or rotate the app's client secret, at any
  time, and the integration will stop working until it's updated.
- **Polling only.** Data is only as fresh as the bike's last report. The 2G module only reports in from
  time to time, so polling faster than it reports gives no fresher data.
- **Separate login from the phone app.** Logging in here creates a token chain independent of the
  one in the Geocover app. Never copy tokens between them: the refresh token is single use and
  rotates on every refresh, so two programs sharing one would log each other out.
- The refresh token is saved to the config entry every time it rotates. If Home Assistant is killed
  in the second between a refresh and the save, or a refresh response is lost on the network, the
  chain breaks and you'll be asked to log in again.
- A bike whose battery has never reported (for example a newly registered one, before it's switched
  on) shows the battery as *unknown*. The API reports 0% in that case.
- **The odometer over-counts after each ride.** The API's odometer goes up live while you ride,
  then Conneqtech adds the ride's distance again when it closes the ride. On a 16 km test ride
  the bike's display read 279 km while the API reported 295.5 km. The integration shows the
  API's value unchanged; it can't reliably correct it.
- **Rides show up with a delay.** "Ride in progress" turns on a few minutes after you set off and
  off around 15–20 minutes after you stop (server-side). The last-ride sensors update on the poll
  where it turns off.
- The bike reports roughly every 5 minutes while powered on and not at all while switched off, so
  the default 5-minute polling matches it.

## Privacy

The bike payload includes the IMEI, frame number, a Bluetooth pairing secret and activation codes.
Downloaded diagnostics redact these, along with tokens, coordinates and account details. Tokens are
never logged.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/pytest
```

The tests mock pygeocover and never call the real API. For a manual check against the live API,
`scripts/live_probe.py` logs in and dumps every read endpoint. Its tokens are kept in `.live/`, which
is git-ignored.

## Credits

- [pygeocover](https://github.com/3615nulsi/pygeocover) by 3615nulsi (MIT), which did the API
  reverse engineering.
- Not affiliated with Decathlon or Conneqtech.
