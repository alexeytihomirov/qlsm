from pathlib import Path


def test_cursor_seed_creates_live_file_without_importing_old_history():
    task_file = (
        Path(__file__).parents[1]
        / 'ansible/playbooks/tasks/server_log_archiving.yml'
    ).read_text()
    seed_start = task_file.index('if [ ! -s "$cursor" ]; then')
    seed_end = task_file.index('          fi', seed_start)
    seed_branch = task_file[seed_start:seed_end]

    assert 'journalctl -u "$unit" -n0 --cursor-file="$cursor"' in seed_branch
    assert 'touch "${logdir}/server.log"' in seed_branch
    assert 'continue' in seed_branch


def test_export_lock_wait_is_bounded_and_fetch_surfaces_timeout():
    repo_root = Path(__file__).parents[1]
    task_file = (
        repo_root / 'ansible/playbooks/tasks/server_log_archiving.yml'
    ).read_text()
    fetch_playbook = (
        repo_root / 'ansible/playbooks/fetch_server_log_archive.yml'
    ).read_text()
    flush_start = fetch_playbook.index(
        '- name: Flush journal into the server log archive'
    )
    flush_end = fetch_playbook.index(
        '- name: Check if the requested server log file exists', flush_start
    )
    flush_task = fetch_playbook[flush_start:flush_end]

    assert 'flock -w 10 9 || exit 1' in task_file
    assert 'failed_when: false' not in flush_task
