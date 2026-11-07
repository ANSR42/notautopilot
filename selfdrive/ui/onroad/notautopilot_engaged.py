"""When the notautopilot wheel badge may be shown.

OpenpilotState.enabled is the only state in which openpilot is engaged
and is not in pre-enable, driver override, or soft-disable. Always On
Lateral can command steering while the state stays disabled, so that
state check keeps the badge off. When this install uses openpilot
longitudinal control, longitudinal must be active as well.
"""

from cereal import log


OpenpilotState = log.SelfdriveState.OpenpilotState

ENGAGED_ICON_ASSET = "notautopilot/icon.png"
ENGAGED_ICON_NATIVE = 1024
# Display crop of the committed badge. The file itself is not modified.
ENGAGED_ICON_CROP = (91, 93, 840)


def show_notautopilot_engaged_icon(state, lat_active: bool, long_active: bool,
                                   openpilot_longitudinal: bool) -> bool:
  if state != OpenpilotState.enabled:
    return False
  if not lat_active:
    return False
  if openpilot_longitudinal and not long_active:
    return False
  return True


def engaged_icon_from_ui(ui) -> bool:
  sm = getattr(ui, "sm", {})
  selfdrive_state = sm["selfdriveState"] if _contains(sm, "selfdriveState") else None
  car_control = None
  valid = getattr(sm, "valid", None)
  if isinstance(valid, dict) and valid.get("carControl") and _contains(sm, "carControl"):
    car_control = sm["carControl"]
  return show_notautopilot_engaged_icon(
    getattr(selfdrive_state, "state", None),
    bool(getattr(car_control, "latActive", False)),
    bool(getattr(car_control, "longActive", False)),
    bool(getattr(ui, "has_longitudinal_control", False)),
  )


def engaged_icon_source(texture_width: float, texture_height: float) -> tuple[float, float, float, float]:
  left, top, side = ENGAGED_ICON_CROP
  scale_x = texture_width / ENGAGED_ICON_NATIVE
  scale_y = texture_height / ENGAGED_ICON_NATIVE
  return left * scale_x, top * scale_y, side * scale_x, side * scale_y


def _contains(container, key) -> bool:
  try:
    return key in container
  except TypeError:
    return False
