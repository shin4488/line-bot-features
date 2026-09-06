"""Explicit post-deploy smoke test: sends one synthetic Sentry error, no LINE/DB I/O."""
import monitoring


class MonitoringSmokeTest(Exception):
    pass


def main():
    if not monitoring.init_monitoring():
        raise SystemExit("Sentry is disabled. Configure SENTRY_DSN first.")
    try:
        raise MonitoringSmokeTest("Synthetic monitoring verification")
    except MonitoringSmokeTest as error:
        event_id = monitoring.capture_exception(error)
    monitoring.flush()
    print("Sentry event ID:", event_id)
    print("Confirm receipt in Sentry; an event ID alone does not prove delivery.")


if __name__ == "__main__":
    main()
