#!/bin/bash
# WINGMAN run script — Kingsfield Lawfare
cd ~/code/kingsfield/wingman
set -a && source ../.env && set +a
.venv/bin/python wingman_live.py
