from cisco_to_ansible import build_firmware_preamble


def test_preamble_has_fifteen_tasks():
    tasks = build_firmware_preamble()
    assert len(tasks) == 15


def test_preamble_task_names_in_expected_order():
    tasks = build_firmware_preamble()
    names = [t.name for t in tasks]
    assert names[0].lower().startswith("firmware: gather pre-upgrade facts")
    assert "decide" in names[1].lower() or "upgrade needed" in names[1].lower()
    assert "verify image exists" in names[2].lower()
    assert "verify free space" in names[3].lower()
    assert "pre-upgrade show version" in names[4].lower()
    assert "copy" in names[5].lower() and "usb" in names[5].lower()
    assert "md5" in names[6].lower()
    assert "boot variable" in names[7].lower() or "boot system" in names[7].lower()
    assert "write memory" in names[8].lower() or "save running" in names[8].lower()
    assert "prior image" in names[9].lower() or "remember" in names[9].lower()
    assert "reload" in names[10].lower()
    assert "pause" in names[11].lower() or "wait" in names[11].lower()
    assert "wait for connection" in names[12].lower()
    assert "post-upgrade" in names[13].lower()
    assert "capture post" in names[14].lower() or "cleanup" in names[14].lower()


def test_preamble_uses_ansible_vars_not_hardcoded():
    tasks = build_firmware_preamble()
    joined_params = repr([t.params for t in tasks])
    for required in ("firmware_image", "firmware_md5", "firmware_target_version",
                     "firmware_usb_device", "firmware_flash_device",
                     "firmware_reload_countdown", "firmware_reload_timeout"):
        assert required in joined_params, f"missing var: {required}"


def test_preamble_gated_by_upgrade_flag():
    tasks = build_firmware_preamble()
    gated = [t for t in tasks if any(k == "when" for k, _ in t.params)]
    # Tasks after #2 (decision) must have when: firmware_upgrade_needed
    assert len(gated) >= 12, f"expected >=12 gated tasks, got {len(gated)}"
