# Athena is telemetry. Its crashes still get a timestamped log, but they must
# not write error.txt. That file latches openpilotCrashed as a no-entry and
# makes controlsd cancel a Tesla pcmEnable. Vehicle checks are unchanged.
ATHENA_LATCHES_ENGAGEMENT = False
