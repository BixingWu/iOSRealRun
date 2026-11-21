"""Version shared by the desktop app and portable builds."""

import sys

VERSION = "0.2.0-beta.5"
BUILD_ID = getattr(sys, "_iosrealrun_build_id", None)
