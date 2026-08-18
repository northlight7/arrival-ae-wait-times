# Arrival

Honest A&E waiting-time forecasts for Hong Kong.

## How it works

The Hospital Authority publishes one prospective estimate per hospital of how
long a triage-III patient arriving now will wait. Arrival samples that figure
every 15 minutes, builds a history for each hospital, triage class and hour of
week, and shows today's estimate as an interval against that history, together
with the 1-in-20 long wait and travel time. Each department is compared with
its own usual range at this hour, so you can see at a glance whether today is
normal.

## Where the data comes from

The Hospital Authority's public A&E waiting-time feed, sampled every 15
minutes and stored locally in `data/`. Nothing is simulated and no account is
needed.

## Run it

The launchers install everything they need into this folder. No admin
password, no system Python, no Node.

- **macOS** — double-click `LAUNCHER.command`, or run `./LAUNCHER.sh`
- **Windows** — double-click `LAUNCHER.bat`

Then open <http://127.0.0.1:8094>.

## Not medical advice

This forecasts queues, not conditions, and cannot triage anyone. In an
emergency in Hong Kong, call 999.
