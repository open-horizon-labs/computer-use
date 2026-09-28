"""Mutation checks for option B (look, then plan; CE-FACADE-005): apply each tempting WRONG patch to a temporary copy of facade/ and prove that
the named tests FAIL BY ASSERTION (a test that errors for an unrelated reason does not count as catching it). Exit nonzero if any wrong patch
survives or is only caught by an error.

Needs the facade requirements (mcp) for the budget tests: run with .venv-facade/bin/python. Fakes only; nothing touches the desktop, a model or the network.
The real tree is never modified.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOK_PLAN = ['test_look', 'test_plan']

# name: (why this patch is tempting, [(file, old, new)], tests that must FAIL by assertion)
MUTATIONS = {
    'nuextract_in_the_default_look': (
        'run the extraction model in every look "to be helpful"',
        [('look.py', "        if fields is not None and shown:", "        fields = fields or {'vendor': {'description': 'vendor'}}\n        if shown:")],
        ['test_look.LookReal.test_the_default_look_calls_no_model_and_no_reader', 'test_look.LookFields.test_without_fields_the_reader_is_never_called']),
    'silent_truncation': (
        'slice the records and say nothing about what was cut',
        [('look.py', "    truncated = {'records': extras['records_over_cap'], 'lines': lines_lost, 'bytes': extras.setdefault('rows_total', len(rows)) - keep}",
          "    truncated = {'records': 0, 'lines': 0, 'bytes': 0}\n    extras['records_over_cap'] = 0")],
        ['test_look.LookShapes.test_a_100_row_list_is_bounded_and_every_cut_is_counted_never_silent',
         'test_look.LookShapes.test_max_bytes_bounds_the_response_and_reports_the_records_it_dropped',
         'test_look.LookShapes.test_long_and_many_lines_are_cut_visibly_and_counted']),
    'lines_where_without_look_id': (
        'look_id optional: with none, run the filter over the current page',
        [('plan.py', "    if needs_look:\n        if look_id is None:", "    if needs_look:\n        if False:"),
         ('plan.py', "        if look_id not in f.looks:", "        if False:"),
         ('plan.py', "            channel['lines_where']['pid_window'] = (look['pid'], look['window_id'])", "            channel['lines_where']['pid_window'] = (look['pid'], look['window_id']) if look else (ctx['pid'], ctx['window_id'])"),
         ('plan.py', "    look = spec['look']\n    analysis = lk.analyze(f, state)\n    rows, _, _ = lk.select(analysis, look['terms'], cap=look['n'])\n    if lk.view_id(rows) != spec['look_id']:",
          "    look = spec['look'] or {'terms': [], 'n': 10 ** 6}\n    analysis = lk.analyze(f, state)\n    rows, _, _ = lk.select(analysis, look['terms'], cap=look['n'])\n    if spec['look'] and lk.view_id(rows) != spec['look_id']:")],
        ['test_plan.Validation.test_where_lines_without_a_look_id_is_refused_before_any_click_and_points_at_cua_look',
         'test_plan.Validation.test_an_invented_look_id_is_refused']),
    'null_expect_on_a_non_final_step': (
        'allow expect=null anywhere',
        [('plan.py', "        if kind != 'verify' and 'expect' not in step and not final:", "        if kind != 'verify' and 'expect' not in step and False:")],
        ['test_plan.Validation.test_null_expect_on_a_non_final_step_is_refused_before_any_click']),
    'steps_continue_after_a_non_done_step': (
        'keep executing the remaining steps after a failed one',
        [('plan.py', "        if not ok:\n            break\n    ran_actions", "        if not ok:\n            pass\n    ran_actions")],
        ['test_plan.WizardPlans.test_the_plan_stops_at_the_first_step_that_is_not_done_and_never_runs_the_rest',
         'test_plan.WizardPlans.test_a_stale_page_mid_plan_stops_at_that_step_after_one_bounded_rerun']),
    'selection_reuse_across_steps': (
        'bind every step on the first observation and replay it',
        [('core.py', "            snapshot = guarded('observe', lambda: self.observe(pid_, window_, timeout=remaining()))['snapshot'];state = self.state(snapshot)\n            count('observe', 'cua-driver')\n            self.reject_answer_leak(state, goal)",
          "            if plan is not None and plan.get('sticky'):\n                snapshot = plan['sticky'];self.latest[(pid_, window_)] = snapshot\n            else:snapshot = guarded('observe', lambda: self.observe(pid_, window_, timeout=remaining()))['snapshot']\n            if plan is not None:plan.setdefault('first_snapshot', snapshot)\n            state = self.state(snapshot)\n            count('observe', 'cua-driver')\n            self.reject_answer_leak(state, goal)"),
         ('plan.py', "        channel = {'goal': goal, 'out': {}}", "        channel = {'goal': goal, 'out': {}, 'sticky': carry.get('first')}"),
         ('plan.py', "        carry['before'] = channel['out'].get('before')", "        carry.setdefault('first', channel.get('first_snapshot'))\n        carry['before'] = channel['out'].get('before')")],
        ['test_plan.WizardPlans.test_three_steps_run_in_one_call_each_on_a_fresh_observation_with_a_new_selection']),
    'destructive_control_not_checked_at_resolve_time': (
        'guard only the literal control label',
        [('core.py', "                bad = planmod.destructive_verbs(action.get('name') or '', plan['goal'])", "                bad = []")],
        ['test_plan.DestructiveAtResolve.test_a_whole_word_prefix_that_resolves_to_a_destructive_control_is_never_pressed',
         'test_plan.DestructiveAtResolve.test_a_record_whose_only_control_is_destructive_is_not_pressed_when_the_goal_never_asked']),
    'destructive_control_not_checked_at_validation': (
        'no destructive guard on the literal label',
        [('plan.py', "            bad = destructive_verbs(label, goal) if label else []", "            bad = []")],
        ['test_plan.Validation.test_a_destructive_literal_control_is_refused_unless_the_plan_goal_says_so',
         'test_plan.Validation.test_a_destructive_confirm_label_is_refused_unless_the_goal_says_so']),
    'several_line_matches_click_the_first': (
        'break ties instead of deferring',
        [('plan.py', "    if len(matched) != 1:", "    if not matched:"),
         ('plan.py', "    only = matched[0]\n", "    only = matched[0]\n")],
        ['test_plan.BookingPlans.test_several_matches_defer_with_their_lines_and_the_chooser_is_never_asked',
         'test_plan.InvoicePlans.test_a_vendor_only_filter_matches_the_near_duplicates_and_clicks_nothing']),
    'filter_over_records_the_look_did_not_show': (
        'match against every record on the page',
        [('plan.py', "    visible = {r['rec']['root']: r for r in rows}", "    visible = {r['rec']['root']: r for r in lk.select(analysis, [], cap=None)[0]}")],
        ['test_plan.BookingPlans.test_a_record_the_look_did_not_show_is_never_a_candidate',
         'test_plan.InvoicePlans.test_the_target_beyond_the_default_cap_is_not_selectable_without_a_focused_look']),
    'page_change_since_look_not_detected': (
        'run the filter over the current lines whatever the look said',
        [('plan.py', "    if lk.view_id(rows) != spec['look_id']:", "    if False:")],
        ['test_plan.BookingPlans.test_page_changed_since_look_defers_and_clicks_nothing']),
    'confirm_by_label_without_identity': (
        'press the confirm label because a dialog appeared',
        [('core.py', "            if verdict == 'partial':return finish(", "            if False:return finish("),
         ('core.py', "            if verdict != 'matched':return finish(", "            if False:return finish(")],
        ['test_plan.OrdersPlans.test_a_dialog_that_shows_only_part_of_the_identity_is_never_pressed',
         'test_plan.OrdersPlans.test_a_dialog_that_belongs_to_another_record_is_never_pressed']),
    'a_click_is_retried': (
        'let the selection be replayed after a failure that may have delivered',
        [('core.py', "        item['used']=True  # Never replay an uncertain side effect.", "        item['used']=False")],
        ['test_plan.WizardPlans.test_a_click_is_never_retried_and_a_driver_failure_on_it_ends_failed_with_uncertain_delivery']),
    'abort_if_ignored': (
        'accept abort_if and never look at it',
        [('plan.py', "        aborted = ctx['pid'] is not None and abort_if and", "        aborted = False and")],
        ['test_plan.WizardPlans.test_abort_if_stops_the_plan_after_the_step_that_shows_it']),
    'plan_budget_cap_missing': (
        'a per-step budget only',
        [('plan.py', "        if remaining <= 0:", "        if False:")],
        ['test_plan.WizardPlans.test_the_plan_wall_budget_stops_before_the_next_step_and_never_clicks_past_it']),
    'look_id_ignores_line_text': (
        'an id that does not depend on what the LLM saw',
        [('look.py', "    return 'lk_' + hashlib.sha1(json.dumps(displayed_lines, ensure_ascii=False).encode()).hexdigest()[:10]", "    return 'lk_' + hashlib.sha1(json.dumps(len(displayed_lines)).encode()).hexdigest()[:10]")],
        ['test_look.LookReal.test_look_id_is_stable_for_the_same_strings_and_changes_when_a_line_changes',
         'test_plan.BookingPlans.test_page_changed_since_look_defers_and_clicks_nothing']),
    'look_clicks_or_scrolls': (
        'reveal more of the page by scrolling during the look',
        [('look.py', "        stage('observe', began)\n        handle = fresh['snapshot']", "        stage('observe', began)\n        f.driver.call('scroll', {'pid': pid, 'window_id': window_id})\n        handle = fresh['snapshot']")],
        ['test_look.LookReal.test_look_is_read_only_no_click_no_window_move']),
    'look_hidden_in_advanced_mode': (
        'register cua_look only inside register_advanced',
        [('server.py', "@mcp.tool(annotations=READ)\ndef cua_look(", "def cua_look(")],
        ['test_budget.ToolSurface.test_surface_is_clean']),
    'primitive_named_in_a_plan_hint': (
        'a hint that sends the LLM to a primitive',
        [('plan.py', "Call cua_do with steps=[{do:\"verify\", expect:<page text that should be visible now>}] to check, or report the state.", "Call cua_verify to check, or report the state.")],
        ['test_plan.BookingPlans.test_an_expect_that_never_appears_is_never_done_and_the_click_is_not_repeated']),
    'primitives_visible_by_default': (
        'drop the CUA_TASK_ADVANCED guard',
        [('server.py', "if ADVANCED:register_advanced()", "register_advanced()")],
        ['test_budget.ToolSurface.test_primitives_registered_by_default_fail', 'test_plan.ServerSurface.test_the_default_surface_is_exactly_cua_do_then_cua_look_and_the_primitives_are_absent']),
    'budget_look_reader': (
        'the default look reads through NuExtract (measured through the real server tools)',
        [('look.py', "        f.looks[response['look_id']] = {", "        try:f.provider('reader').extract({'snapshot_id': state['raw']['snapshot_id'], 'task': 't', 'fields': {'x': 'x'}, 'records': [{'id': 'e1', 'text': 't'}]}, state['raw']['snapshot_id'])\n        except Exception:pass  # the fake reader counts the request before it looks for a pattern\n        f.looks[response['look_id']] = {")],
        ['test_budget.DefaultPathBudget.test_look_then_plan_is_two_calls_with_no_reader_and_no_chooser_on_the_real_trees']),
}


def stage(tmp):
    shutil.copytree(ROOT / 'facade', tmp / 'facade', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('inference', 'skills', 'docs', 'scripts'):
        (tmp / name).symlink_to(ROOT / name)


def run_tests(tmp, names):
    done = subprocess.run([sys.executable, '-m', 'unittest', *names], cwd=str(tmp / 'facade'), capture_output=True, text=True, timeout=600)
    text = done.stdout + done.stderr
    failed = set(re.findall(r'^FAIL: (\w+) \(([\w\.]+)\)', text, re.M))
    errored = set(re.findall(r'^ERROR: (\w+) \(([\w\.]+)\)', text, re.M))
    return done.returncode, {m + '::' + c for m, c in failed}, {m + '::' + c for m, c in errored}, text


def main():
    only = sys.argv[1:]
    bad = 0
    rows = []
    for name, (why, patches, expected) in MUTATIONS.items():
        if only and name not in only:
            continue
        with tempfile.TemporaryDirectory(prefix='cua-mutation-') as raw:
            tmp = Path(raw);stage(tmp)
            for filename, old, new in patches:
                path = tmp / 'facade' / filename;text = path.read_text()
                if text.count(old) != 1:
                    print('%s: patch target not found exactly once in %s: %r' % (name, filename, old[:60]));bad += 1;break
                path.write_text(text.replace(old, new))
            else:
                modules = sorted({e.split('.')[0] for e in expected})
                code, failed, errored, text = run_tests(tmp, modules)
                got = {}
                for e in expected:
                    module, rest = e.split('.', 1);cls, test = rest.rsplit('.', 1)
                    key = '%s::%s.%s.%s' % (test, module, cls, test) if False else None
                    hit = [f for f in failed if f.startswith(test + '::') and f.endswith(module + '.' + cls + '.' + test) or f.startswith(test + '::') and (module + '.' + cls) in f]
                    err = [f for f in errored if f.startswith(test + '::') and (module + '.' + cls) in f]
                    got[e] = 'FAIL' if hit else ('ERROR' if err else 'passed')
                caught = all(v == 'FAIL' for v in got.values())
                rows.append((name, caught, got, len(failed), len(errored)))
                if not caught:
                    bad += 1
    print('%-52s %-8s %s' % ('wrong patch', 'verdict', 'named tests (FAIL = caught by assertion)'))
    for name, caught, got, nfail, nerr in rows:
        print('%-52s %-8s failed=%d errored=%d' % (name, 'CAUGHT' if caught else 'MISSED', nfail, nerr))
        for test, verdict in got.items():
            print('    %-6s %s' % (verdict, test))
    print('%d wrong patches applied, %d not caught by assertion' % (len(rows), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
