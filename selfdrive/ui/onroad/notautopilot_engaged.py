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
AVAILABLE_ICON_ASSET = "notautopilot/icon_available.png"
ENGAGED_ICON_NATIVE = 1024
# Display crop of the committed badge. The file itself is not modified.
ENGAGED_ICON_CROP = (91, 93, 840)
# Sampled from the committed icon disc. Too dark for a road ribbon:
# about 1.6:1 against mid-gray pavement.
BADGE_BLUE_RGB = (27, 77, 163)
# Same hue as the badge, raised so a large path ribbon stays blue and
# clears about 3:1 on dark pavement and about 2.8:1 on mid-gray pavement.
PATH_BLUE_RGB = (89, 150, 255)


def show_notautopilot_engaged_icon(state, lat_active: bool, long_active: bool,
                                   openpilot_longitudinal: bool) -> bool:
  if state != OpenpilotState.enabled:
    return False
  if not lat_active:
    return False
  if openpilot_longitudinal and not long_active:
    return False
  return True


HIDDEN = "hidden"
AVAILABLE = "available"
ENGAGED = "engaged"


def badge_presentation(state, lat_active: bool, long_active: bool, openpilot_longitudinal: bool,
                       engageable, state_valid: bool, car_valid: bool, always_on_lateral: bool) -> str:
  """Custom wheel only. Stock controls and the critical wheel stay with the caller.

  AVAILABLE is selfdriveState.engageable while disengaged. That flag is the
  published "no no-entry event" result, which already includes speed when the
  car port emits belowEngageSpeed. Tesla Model Y does not: minEnableSpeed stays
  at the CarSpecs default of -1 m/s, so this does not invent a 10 mph gate.
  A missing or invalid selfdriveState or carState sample is HIDDEN, because
  car no-entry events are not applied when CAN is invalid.
  """
  if show_notautopilot_engaged_icon(state, lat_active, long_active, openpilot_longitudinal):
    return ENGAGED
  if not state_valid or not car_valid or always_on_lateral:
    return HIDDEN
  if state != OpenpilotState.disabled:
    return HIDDEN
  if engageable is True:
    return AVAILABLE
  return HIDDEN


def badge_presentation_from_ui(ui) -> str:
  sm = getattr(ui, "sm", {})
  valid = getattr(sm, "valid", None)
  state_valid = isinstance(valid, dict) and bool(valid.get("selfdriveState")) and _contains(sm, "selfdriveState")
  car_valid = isinstance(valid, dict) and bool(valid.get("carState")) and _contains(sm, "carState")
  selfdrive_state = sm["selfdriveState"] if state_valid else None
  car_control = None
  if isinstance(valid, dict) and valid.get("carControl") and _contains(sm, "carControl"):
    car_control = sm["carControl"]
  return badge_presentation(
    getattr(selfdrive_state, "state", None),
    bool(getattr(car_control, "latActive", False)),
    bool(getattr(car_control, "longActive", False)),
    bool(getattr(ui, "has_longitudinal_control", False)),
    getattr(selfdrive_state, "engageable", None),
    state_valid,
    car_valid,
    bool(getattr(ui, "always_on_lateral_active", False)),
  )


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


def engaged_path_rgba(rgba: tuple[int, int, int, int], engaged: bool) -> tuple[int, int, int, int]:
  """Keep the path stop's alpha. Replace RGB only while actually engaged."""
  red, green, blue, alpha = rgba
  if not engaged:
    return (red, green, blue, alpha)
  return (*PATH_BLUE_RGB, alpha)


def engaged_icon_source(texture_width: float, texture_height: float) -> tuple[float, float, float, float]:
  left, top, side = ENGAGED_ICON_CROP
  scale_x = texture_width / ENGAGED_ICON_NATIVE
  scale_y = texture_height / ENGAGED_ICON_NATIVE
  return left * scale_x, top * scale_y, side * scale_x, side * scale_y


def _contains(container, key) -> bool:
  """Whether a service name is subscribed.

  A dict stores the samples directly. SubMaster stores them in ``data`` and
  lists the names in ``services``. SubMaster implements ``__getitem__`` and
  not ``__contains__``, so ``name in sm`` calls ``__getitem__(0)`` and raises
  ``KeyError`` instead of stopping at ``IndexError``.
  """
  data = getattr(container, "data", None)
  if isinstance(data, dict):
    return key in data
  services = getattr(container, "services", None)
  if isinstance(services, (list, tuple, set, frozenset)):
    return key in services
  if isinstance(container, dict):
    return key in container
  return False
