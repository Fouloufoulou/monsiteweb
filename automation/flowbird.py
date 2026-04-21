#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flowbird Runner (dual-mode, sans retry auto)
Codes sortie:
0 succès | 4 OTP IMAP | 5 OTP timeout | 6 Achat KO | 7 Driver mort | 8 Login KO | 9 State inconnu | 1 Exception
"""

import os
import sys
import argparse
import configparser
import pathlib
import logging
import time
from flowbird_core.utils import (
    init_logger,
    default_screenshot_path,
    dump_failure,
)
from flowbird_core.cdp_stealth import apply_stealth
from flowbird_core.login import login_cdp_and_state, revive_webdriver
from flowbird_core.otp import maybe_handle_otp
from flowbird_core.tickets import detect_ticket_and_schedule
from flowbird_core.achat import run_purchase_flow
from flowbird_core.sb_shim import SBShim


def build_persistent_driver(profile_dir: str, headed: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument("--lang=en-US")
    opts.add_experimental_option("prefs", {"intl.accept_languages": "en,en_US"})
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--window-size=1280,840")
    opts.add_argument("--window-position=20,54")
    if not headed:
        opts.add_argument("--headless=new")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(Navigator.prototype,'webdriver',{get:()=>undefined});"},
    )
    return driver


def prepare_profile_dir(args):
    d = getattr(args, "profile_dir", "") or str(pathlib.Path().resolve() / "chrome_profile")
    os.makedirs(d, exist_ok=True)
    logging.info(f"💾 Profil Chrome persistant: {d}")
    return d


def main():
    init_logger()
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--screenshot", default="")
    ap.add_argument("--config", default="scenario.conf")
    ap.add_argument("--address", default="5 rue des quatre saisons (Noisy le Grand)")
    ap.add_argument("--profile-dir", default="")
    ap.add_argument("--force-uc", action="store_true")  # gardé pour compat, mais on recommande persistent
    args = ap.parse_args()

    if not args.screenshot:
        args.screenshot = default_screenshot_path()

    cfg = configparser.ConfigParser()
    if os.path.isfile(args.config):
        cfg.read(args.config, encoding="utf-8")

    headed = bool(args.headed and not args.headless)
    driver = None
    try:
        # Mode persistant (recommandé)
        profile_dir = prepare_profile_dir(args)
        driver = build_persistent_driver(profile_dir, headed=headed)
        sb = SBShim(driver)

        apply_stealth(sb)

        # 1) Login → état
        state = login_cdp_and_state(sb, cfg)

        # 2) OTP si requis
        state = maybe_handle_otp(sb, driver, cfg, fast=args.fast, initial_state=state)

        # 3) Tickets en cours ?
        if detect_ticket_and_schedule(driver, fast=args.fast):
            try:
                driver.save_screenshot(args.screenshot)
            except Exception:
                pass
            if args.hold:
                time.sleep(args.hold)
            return 0

        # 4) Achat sinon
        ok = run_purchase_flow(driver, args.address)
        try:
            driver.save_screenshot(args.screenshot)
        except Exception:
            pass
        if args.hold:
            time.sleep(args.hold)
        return 0 if ok else 6

    except SystemExit as e:
        return int(getattr(e, "code", 1) or 1)
    except Exception as ex:  # pragma: no cover - runtime safeguard
        logging.error(f"💥 Exception: {ex}")
        if driver:
            dump_failure(driver, "unhandled", try_revive=None)
        return 1
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
