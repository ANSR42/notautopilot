# Stable StarPilot audit

This note records two decisions on Stable and one read-only Tesla CAN audit. No lateral command, lane-change actuation, blinker command, safety check, or car port was changed.

## Base

| Item | Value |
| --- | --- |
| Fork | `ANSR42/notautopilot` (parent `StarPilotHQ/StarPilot`) |
| Branch used as the only base | `StarPilot` |
| Commit | `4a553da9ac22a14e34513c011aed04c1e93b4619` |
| Subject | Keep Galaxy update progress honest through connection failures |
| Upstream check | `StarPilotHQ/StarPilot` branch `StarPilot` is that same commit (committer date `2026-11-04T03:55:55Z`) |
| Dom tip, reference only | `e959f52e25a2cdad16b33035d514a0c491990aa2` (`2026-11-06T19:29:42Z`). Not checked out and not merged |

Dom was not used as the base. Dom car and safety code was not imported. Wolfe files were not modified. Nothing was flashed, installed on a vehicle, or written to `StarPilotHQ/StarPilot`.

Bench tests below are not road-readiness. Controls Mismatch was not reproduced and is not claimed fixed.

## 1. SteerPilot model-path floor: not implemented

The requested control change is an off-by-default floor of about `k = 0.75` on the driving model's share of the lateral path when a lane-centering bias is applied. It is a different control from Lane Centering, E2E Override Strength, and Turn Assist. Setting `LaneCenteringE2EAuthority` to `0.5` is not that floor.

Stable applies lane centering as an additive curvature bias in `selfdrive/controls/lib/lane_centering.py`:

```text
error = target_y - model_y
error *= 1 - e2e_authority * break_in * (1 - lane_authority)   # only when path std is in range
raw = clip(2 * error / lookahead^2, ±0.004)
command = model_curvature + smooth(raw * 0.30)
```

`lane_authority` is `0.20` away from a lane line and rises to `0.50` near one. With the slider at `1.0` and a full break-in, the residual error scale is `0.20` or `0.50`, not `0.75`. With the slider at `0.5`, a full break-in, and `lane_authority = 0.50`, the residual happens to be `0.75`. That coincidence is still the E2E slider, which also depends on path standard deviation and error size. It is not a constant model-contribution floor.

No Stable, public, or Dom lane-centering source reviewed here defines a SteerPilot weight `k ≈ 0.75`. Dom's current lane-centering module uses a default `e2e_authority` of `0.5` and a separate strength multiplier. That is the setting already rejected, and it was not ported.

Three readings of "model contribution floor 0.75" would scale the curvature bias by different amounts:

- Cap the existing `0.30` gain so the lane share is at most `0.25`.
- Scale the geometric error by `0.25` and then still apply the `0.30` gain.
- Scale the lane error by `0.75`, which would make the lane the majority contributor.

Those are not the same steering command. Guessing one of them for a 2020 Model Y would change lateral control without a source for the formula, so the toggle was not added.

Existing lane-centering tests were run on this unchanged tree, without the repo `conftest` and without pytest-xdist:

`38 passed` in `selfdrive/controls/tests/test_lane_centering.py`, `starpilot/common/tests/test_lane_centering_galaxy.py`, and `starpilot/common/tests/test_safe_mode_lane_centering.py`.

No new floor test was added, because there is no implemented floor to lock. Panda and vehicle safety suites were not rebuilt here. They were not weakened.

## 2. StarPilot BT: still blocked, no bridge added

Checked again on 2026-11-07. No Bluetooth bridge, session adapter, or companion route was added. Controls Mismatch is a separate panda safety-model disagreement and is not affected by this gap.

### Version names are different products

| Name | What it is | Verified value |
| --- | --- | --- |
| App Store StarPilot BT | iPhone app, bundle `link.galaxy.bluetooth.natehuby76` | **1.2.2**, iTunes lookup `currentVersionReleaseDate` `2026-11-04T21:10:56Z`, minimum iOS 17.0. Listing: https://apps.apple.com/ca/app/starpilot-bt/id6821039119 |
| Public companion source | `natehuby76/ios-clone` branch `integrated-latest` | Commit `081bd2045ed74e367fcc6eb2d2eb9c03df5597b0` (2026-11-06). Info.plist `CFBundleShortVersionString` is **1.0.6**, not 1.2.2. https://github.com/natehuby76/ios-clone |
| Stable display version | `STARPILOT_DISPLAY_VERSION` in `selfdrive/ui/lib/starpilot_version.py` | **6.7.9** on this tree and on current `StarPilotHQ/StarPilot` branch `StarPilot` |
| openpilot `COMMA_VERSION` | `common/version.h` | **0.11.2** |
| BluePilot `bp-7.0` | A Ford lateral lineage cited in the README | Not this device firmware and not the iPhone app |

There is no firmware or display version `7.0` in Stable or in the current public iOS source. The iPhone app reads a comma `displayVersion` string from `/api/software/status` and does not compare it to 7.0. App Store 1.2.2 is not Stable 6.7.9.

No public commit maps store version 1.2.2 to a source SHA. The repo version train that is public is 1.0.2, 1.0.3, 1.0.5, and 1.0.6. The 1.2.2 binary was not downloaded or diffed, so this tree is not claimed to be compatible with the installed app.

### Accessible protocol, and why it still cannot be backported here

The newest public source does publish a protocol. `GalaxyBluetooth/Wire.swift` and `BluetoothTransport.swift` at `081bd2045ed7` require an INFO payload of 17 bytes starting with `0x01`, then `GET /_bridge/health` with `protocol == 1` and `transport == "bluetooth"`. LAN login in `NetworkTransport.swift` requires `GET /api/auth/session` to return HTTP 200, `authenticated: true`, `localAccess: true`, and a non-empty `galaxy_session` cookie. Pairing calls `GET /api/companion/bluetooth-ready` (`schema == 1`) and `POST /api/bluetooth/action` with `{"operation":"accept_pair"}`. Galaxy screens require `GET /api/companion/web-manifest` whose files include `index.html`, `js/boot.js`, `js/app.js`, and `data/catalog.json` (`GalaxyAssetStore.swift`).

Stable does not provide those routes. It does provide `GET /api/bluetooth/status`, `POST /api/bluetooth/<operation>` for audio and device operations, `GET /api/galaxy/status`, `GET /api/galaxy/session`, and `GET`/`PUT /api/params`. `GET /api/galaxy/session` returns `paired`, `sessionToken`, and `cookieName`. It does not return `authenticated` or `localAccess`, and it does not set the cookie the app requires.

Other routes the same source calls, and Stable does not define, include `/api/local-access`, `/api/device/state`, `/api/software/status`, `/api/system/monitor`, `/api/models/status`, `/api/settings/pages/`, `/api/settings/preview`, `/api/settings/confirm`, `/api/companion/location`, `/api/companion/navigation`, and `/api/navigation/status`. Those belong to the Dom/SecretGood Galaxy surface. Adding stub responses would not be the app's protocol. Porting that surface would replace Stable Galaxy and navigation behavior, which this change does not do.

A GATT server alone would also be incomplete: after the health check the app issues those HTTP calls. No bridge code was added, and no new unauthenticated settings route was added.

What still requires a physical iPhone and comma, after a source SHA for store 1.2.2 exists and Stable grows the real session, pairing, and manifest contracts: pairing, reconnect, and a check that settings writes stay behind the pairing key. That test was not run.

## 3. Tesla side occupancy and lane-change checks

Read-only. No automatic lane change, blinker command, or safety bypass was added or enabled. Code that contains a signal is not the same thing as that signal having been checked on a 2020 Tesla Model Y HW3.

### What the car port publishes

Model Y, including the documented HW3 years 2020–23, uses platform `TESLA_MODEL_Y` and DBC `tesla_model3_party`. The blind-spot lines do not branch on HW3 versus HW4.

The only side-occupancy fields copied into `carState` are two booleans:

```198:200:opendbc_repo/opendbc/car/tesla/carstate.py
    # Blindspot
    ret.leftBlindspot = cp_ap_party.vl["DAS_status"]["DAS_blindSpotRearLeft"] != 0
    ret.rightBlindspot = cp_ap_party.vl["DAS_status"]["DAS_blindSpotRearRight"] != 0
```

| Item | Stable source |
| --- | --- |
| CAN id | `923` (`0x39B`), message `DAS_status`, 8 bytes |
| DBC | [`opendbc_repo/opendbc/dbc/tesla_model3_party.dbc`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/dbc/tesla_model3_party.dbc#L267-L293) |
| Signals | `DAS_blindSpotRearLeft` bits 4–5; `DAS_blindSpotRearRight` bits 6–7. Both are 2-bit unsigned, factor 1, range 0–3 |
| Enum | [`L465-L466`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/dbc/tesla_model3_party.dbc#L465-L466): `0 NO_WARNING`, `1 WARNING_LEVEL_1`, `2 WARNING_LEVEL_2`, `3 SNA` |
| Parser bus | `CANBUS.autopilot_party` = **2**, DBC still `tesla_model3_party`. [`values.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/car/tesla/values.py#L96-L100), [`carstate.py` parsers](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/car/tesla/carstate.py#L314-L319) |
| `carState` fields | [`cereal/car.capnp`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/cereal/car.capnp#L227-L228) `leftBlindspot` and `rightBlindspot`, both `Bool` |

`!= 0` collapses level 1, level 2, and `SNA` into `true`. `NO_WARNING` is the only `false`. There is no separate unknown, stale, or quality field on `carState`.

The same message also defines signals this port does **not** copy:

- `DAS_sideCollisionWarning`: `NONE`, `WARN_LEFT`, `WARN_RIGHT`, `WARN_LEFT_RIGHT` ([L457](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/dbc/tesla_model3_party.dbc#L457))
- `DAS_sideCollisionAvoid`: `NONE`, `AVOID_LEFT`, `AVOID_RIGHT`, `SNA` ([L458](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/dbc/tesla_model3_party.dbc#L458))
- `DAS_sideCollisionInhibit`: `NO_INHIBIT` or `INHIBIT` ([L456](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/dbc/tesla_model3_party.dbc#L456))
- `DAS_autoLaneChangeState`, including `ALC_BLOCKED_VEH_TTC_L`, `ALC_BLOCKED_VEH_TTC_R`, `ALC_BLOCKED_VEH_TTC_AND_USS_L/R`, and `ALC_SNA` ([L451](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/dbc/tesla_model3_party.dbc#L451))

Those names show Tesla's own lane-change state machine has time-to-collision and ultrasonic words. Stable does not read them. The two blind-spot bits are warning levels, not a distance, relative speed, or closing rate.

`tesla_can.dbc` repeats the same two bits on message `921 AutopilotStatus`. Model Y does not use that DBC. Legacy Model S HW1 `update_legacy` never assigns `leftBlindspot` or `rightBlindspot`.

Dom's Tesla `carstate.py` at the Dom tip above maps the same two signals with the same `!= 0` test ([Dom lines 141–143](https://github.com/StarPilotHQ/StarPilot/blob/e959f52e25a2cdad16b33035d514a0c491990aa2/opendbc_repo/opendbc/car/tesla/carstate.py#L141-L143)). That was comparison only. It does not add rear-approach speed, and it was not imported.

### Freshness, health, unknown, and stale

`DAS_status` is not in the parser's initial message list. The first `vl["DAS_status"]` lookup registers it ([`parser.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/can/parser.py#L117-L125)). Registration happens in `CarState.update`, which runs **after** that cycle's `CANParser.update` ([`interfaces.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/car/interfaces.py#L413-L423)). The first cycle therefore still has the default value `0` (`NO_WARNING` / clear) and no timestamp.

After registration:

- `DAS_statusChecksum` and `DAS_statusCounter` are checked. The DBC name starts with `tesla_`, so a `*Checksum` signal uses `tesla_checksum` and a `*Counter` signal is a counter ([`dbc.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/can/dbc.py#L158-L163), [`teslacan.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/car/tesla/teslacan.py#L49-L55)).
- A bad checksum or a rejected counter does not update the stored value or the timestamp. Five bad counters make `can_valid` false (`MAX_BAD_COUNTER = 5`).
- Until a rate is learned, the alive threshold is 10 seconds (assumed 1 Hz times 10). After at least three timestamps, the threshold becomes `10 / measured_frequency` seconds, with frequency capped at 100 Hz, so the shortest threshold is 0.1 s. The party DBC does not declare a cycle time for `DAS_status`. The rate on a 2020 HW3 car was not measured.
- No timestamp yet means the message is invalid immediately. A timestamp older than the threshold also means invalid.
- `carState.canValid` is true only when every registered message on every parser is valid, and it stays true for the first four consecutive invalid evaluations (`CAN_INVALID_CNT = 5`). `canTimeout` is the bus-level timeout, which is not the same flag as one stale `DAS_status`.
- While invalid, the last accepted raw value remains in `vl`. Lane-change code reads the bool, not the timestamp. A last `NO_WARNING` therefore stays "clear" through the timeout window. A last warning or `SNA` stays "occupied" through that same window.
- `SNA` is not represented as unknown. It is occupied. Before the first accepted frame, the default is clear, not unknown.

There is no Tesla blind-spot unit test in this tree. Nothing here shows that a 2020 Model Y HW3 actually transmits id `923` on bus 2 with these four enum values.

### Rear-approaching traffic and closing speed

Not covered by the mapped signals.

- The published values are warning levels. They do not carry range, range rate, or which of level 1 and level 2 was set.
- Model 3 and Model Y set `radarUnavailable = True` ([`interface.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/opendbc_repo/opendbc/car/tesla/interface.py#L65-L66)). The Bosch radar parser, which does have `LongSpeed` and `LatSpeed`, is not started for this car.
- Forward-lead closing speed in the longitudinal planner is the lead's longitudinal gap. It is not a side or rear gap. Blind-spot booleans only suppress a lane-change merge accel floor ([`longitudinal_planner.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/selfdrive/controls/lib/longitudinal_planner.py#L1972-L1990)) and a shorter following gap ([`starpilot_following.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/starpilot/controls/lib/starpilot_following.py#L187-L195)).
- Stock `DAS_autoLaneChangeState` TTC names are unread, so they are not a measured closing speed either.

### Existing lane-change checks

These checks already exist. This audit does not enable them as an automatic pass-slow-traffic feature and does not add a new one.

1. `DesireHelper` blocks only the transition from `preLaneChange` to `laneChangeStarting` when the blinker-side `carState` bool is true ([`desire_helper.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/selfdrive/controls/lib/desire_helper.py#L343-L367)). It does not sample the bool again in `laneChangeStarting` or `laneChangeFinishing`. It does not read V-ASM. It also requires one blinker, speed at or above `minimum_lane_change_speed`, lateral control, the lane-change toggle, a lane-width threshold, and either steering torque or a nudgeless delay.
2. `selfdrived` can show `laneChangeBlocked` during `preLaneChange` from the CAN bool **or** fresh V-ASM ([`selfdrived.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/selfdrive/selfdrived/selfdrived.py#L608-L638)). That is an alert. The desire state machine does not see V-ASM, so a vision-only detection does not by itself stop the maneuver.
3. V-ASM is the driver-camera adjacent-vehicle detector, not Tesla CAN. `get_fresh_vasm_state` returns clear if the update is missing, in the future, or older than 3.0 seconds ([`vision_bsm.py`](https://github.com/ANSR42/notautopilot/blob/4a553da9ac22a14e34513c011aed04c1e93b4619/starpilot/common/vision_bsm.py#L6-L22)).
4. The Tesla panda safety model does not take these blind-spot bits. `controlsMismatch` in `selfdrived` is a safety-model or safety-parameter disagreement with the panda, not a blind-spot result.

### Code present versus a 2020 Model Y HW3

| Available in this Stable tree | Not established on a 2020 Model Y HW3 |
| --- | --- |
| DBC layout and enum names for the two rear blind-spot bits | That this car emits id `923` on bus 2 |
| Mapping of any non-zero value, including `SNA`, to `carState` booleans | Which enum appears for an empty lane, a alongside vehicle, and a fast approach from the rear |
| Parser checksum, counter, and alive-timeout behavior | The real message rate, so the timeout in seconds is unknown |
| Lane-change start blocked by that boolean | That the boolean tracks the traffic a pass-slow-traffic feature would need |
| Unread TTC words inside `DAS_autoLaneChangeState` | A numeric gap or closing speed |

No route from that car was replayed. No CAN capture was decoded. No on-road or parked-car check was done.

### Offline shadow checks before any actuation

Do these before any change that could steer, blink, or alter lane-change state. Do not treat them as approval to implement that change.

1. Log, without feeding control, the raw 2-bit values, checksum and counter result, message age, `canValid`, and the unread `DAS_sideCollision*` and `DAS_autoLaneChangeState` enums from an existing route or a parked capture.
2. Measure the observed period of id `923` on bus 2 before relying on the learned 10-period timeout.
3. Label adjacent traffic separately, including a vehicle closing from behind. Score the bool against those labels. Confirm whether `SNA` happens in normal driving. A match on a static alongside car still would not show closing speed, because the bits do not contain speed.
4. Keep the shadow log off `carState` and off `DesireHelper` until that comparison is reviewed. V-ASM agreement is a second sensor, not a definition of the CAN enum.
5. Leave panda safety, blinker commands, and the current lane-change gates unchanged.

Unresolved before any future off-by-default feature: a verified decode on this vehicle, a defined unknown state that is not "clear", a measured timeout, and an actual side closing-speed source. None of those is in the current mapping.
