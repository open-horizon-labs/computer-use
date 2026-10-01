"""Mutation checks for option B (look, then plan; CE-FACADE-005): apply each tempting WRONG patch to a temporary copy of computer_use/ and prove that
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
        [('look.py', "trunc = {'records': extras['records_over_cap'], 'lines': lost, 'bytes': bytes_cut}", "trunc = {'records': 0, 'lines': 0, 'bytes': 0}")],
        ['test_look.LookShapes.test_a_100_row_list_is_bounded_and_every_cut_is_counted_never_silent',
         'test_look.LookShapes.test_max_bytes_bounds_the_response_and_reports_the_records_it_dropped',
         'test_look.LookShapes.test_long_and_many_lines_are_cut_visibly_and_counted']),
    'lines_where_without_look_id': (
        'look_id optional: with none, run the filter over the current page',
        [('plan.py', "    if needs_look:\n        if look_id is None:", "    if needs_look:\n        if False:"),
         ('plan.py', "        if not any(key[2] == look_id for key in f.looks):", "        if False:"),
         ('plan.py', "    if look_id is not None and not any(key[2] == look_id for key in f.looks):", "    if False:"),
         ('core.py', "                if lines_where['look'] is None:\n                    raise Gap(", "                if False:\n                    raise Gap("),
         ('plan.py', "    look = spec['look']\n    opts = look.get('opts', lk.DEFAULT_OPTS)", "    look = spec['look'] or {'terms': [], 'n': 10 ** 6}\n    opts = look.get('opts', lk.DEFAULT_OPTS)"),
         ('plan.py', "    if not same:\n        return {'defer': {'reason': 'page_changed_since_look'", "    if spec['look'] and not same:\n        return {'defer': {'reason': 'page_changed_since_look'")],
        ['test_plan.Validation.test_where_lines_without_a_look_id_is_refused_before_any_click_and_points_at_look',
         'test_plan.Validation.test_an_invented_look_id_is_refused']),
    'null_expect_on_a_non_final_step': (
        'allow expect=null anywhere',
        [('plan.py', "        if kind not in ('verify', 'close_tab', 'read_pages', 'resize', 'swipe') and 'expect' not in step and not final:", "        if kind not in ('verify', 'close_tab', 'read_pages', 'resize', 'swipe') and 'expect' not in step and False:")],
        ['test_plan.Validation.test_null_expect_on_a_non_final_step_is_refused_before_any_click']),
    'steps_continue_after_a_non_done_step': (
        'keep executing the remaining steps after a failed one',
        [('plan.py', "        if not ok:\n            break\n    ran_actions", "        if not ok:\n            pass\n    ran_actions")],
        ['test_plan.WizardPlans.test_the_plan_stops_at_the_first_step_that_is_not_done_and_never_runs_the_rest',
         'test_plan.WizardPlans.test_a_stale_page_mid_plan_stops_at_that_step_after_one_bounded_rerun']),
    'selection_reuse_across_steps': (
        'bind every step on the first observation and replay it',
        [('core.py', "            snapshot = seen['snapshot'];state = self.state(snapshot)\n            self.reject_answer_leak(state, goal)",
          "            if plan is not None and plan.get('sticky'):\n                snapshot = plan['sticky'];self.latest[(pid_, window_)] = snapshot\n            else:snapshot = seen['snapshot']\n            if plan is not None:plan.setdefault('first_snapshot', snapshot)\n            state = self.state(snapshot)\n            self.reject_answer_leak(state, goal)"),
         ('plan.py', "        channel = {'goal': goal, 'out': {}, 'allow': step.get('allow_destructive'), 'look_id': look_id}", "        channel = {'goal': goal, 'out': {}, 'allow': step.get('allow_destructive'), 'look_id': look_id, 'sticky': carry.get('first')}"),
         ('plan.py', "        carry['before'] = channel['out'].get('before')", "        carry.setdefault('first', channel.get('first_snapshot'))\n        carry['before'] = channel['out'].get('before')")],
        ['test_plan.WizardPlans.test_three_steps_run_in_one_call_each_on_a_fresh_observation_with_a_new_selection']),
    'destructive_control_not_checked_at_resolve_time': (
        'guard only the literal control label',
        [('core.py', "                bad = planmod.destructive_verbs(action.get('name') or '')", "                bad = []")],
        ['test_plan.DestructiveAtResolve.test_a_whole_word_prefix_that_resolves_to_a_destructive_control_is_never_pressed',
         'test_plan.DestructiveAtResolve.test_a_record_whose_only_control_is_destructive_is_not_pressed_without_the_declaration']),
    'destructive_control_not_checked_at_validation': (
        'no destructive guard on the literal label',
        [('plan.py', "            bad = destructive_verbs(label) if label else []", "            bad = []")],
        ['test_plan.Validation.test_a_destructive_literal_control_is_refused_unless_the_plan_goal_says_so',
         'test_plan.Validation.test_a_destructive_confirm_label_is_refused_unless_the_step_declares_it']),
    'several_line_matches_click_the_first': (
        'break ties instead of deferring',
        [('plan.py', "    if len(matched) != 1 or len(shown_matches) != 1:", "    if not matched:")],
        ['test_plan.BookingPlans.test_several_matches_defer_with_their_lines_and_the_chooser_is_never_asked',
         'test_plan.InvoicePlans.test_a_vendor_only_filter_matches_the_near_duplicates_and_clicks_nothing']),
    'filter_over_records_the_look_did_not_show': (
        'match against every record on the page',
        [('plan.py', "    if len(matched) != 1 or len(shown_matches) != 1:", "    if len(matched) != 1:")],
        ['test_plan.BookingPlans.test_a_record_the_look_did_not_show_is_never_a_candidate',
         'test_plan.InvoicePlans.test_the_target_beyond_the_default_cap_is_not_selectable_without_a_focused_look']),
    'page_change_since_look_not_detected': (
        'run the filter over the current lines whatever the look said',
        [('plan.py', "    if not same:\n        return {'defer': {'reason': 'page_changed_since_look'", "    if False:\n        return {'defer': {'reason': 'page_changed_since_look'")],
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
        [('look.py', "json.dumps([title or '', list(headings), full_lines, list(controls)], ensure_ascii=False, default=str)", "json.dumps(len(full_lines))")],
        ['test_look.LookReal.test_look_id_is_stable_for_the_same_strings_and_changes_when_a_line_changes',
         'test_plan.BookingPlans.test_page_changed_since_look_defers_and_clicks_nothing']),
    'look_clicks_or_scrolls': (
        'reveal more of the page by scrolling during the look',
        [('look.py', "        stage('observe', began)\n        handle = fresh['snapshot']", "        stage('observe', began)\n        f.driver.call('scroll', {'pid': pid, 'window_id': window_id})\n        handle = fresh['snapshot']")],
        ['test_look.LookReal.test_look_is_read_only_no_click_no_window_move']),
    'look_hidden_in_advanced_mode': (
        'register look only inside register_advanced',
        [('server.py', "@mcp.tool(annotations=READ)\ndef look(", "def look(")],
        ['test_budget.ToolSurface.test_surface_is_clean']),
    'primitive_named_in_a_plan_hint': (
        'a hint that sends the LLM to a primitive',
        [('plan.py', "Call do with steps=[{do:\"verify\", expect:<page text that should be visible now>}] to check, or report the state.", "Call verify to check, or report the state.")],
        ['test_plan.BookingPlans.test_an_expect_that_never_appears_is_never_done_and_the_click_is_not_repeated']),
    'primitives_visible_by_default': (
        'drop the CUA_TASK_ADVANCED guard',
        [('server.py', "if ADVANCED:register_advanced()", "register_advanced()")],
        ['test_budget.ToolSurface.test_primitives_registered_by_default_fail', 'test_plan.ServerSurface.test_the_default_surface_is_exactly_do_then_look_and_the_primitives_are_absent']),
    'kill_a_live_owners_browser': (
        'treat a live owner\'s profile as stale and kill what uses it (#91)',
        [('agent_browser.py', "        return bool(found and owner.get('start') == found[0] and owner.get('command') == found[1])", "        return False")],
        ['test_agent_browser.Two.test_a_second_server_never_kills_the_live_owners_browser_and_uses_its_own_profile']),
    'resize_a_window_that_is_not_the_agent_browser': (
        'resize whatever window the caller names (#78)',
        [('agent_browser.py', "(ctx.get('pid') is not None and (not self.alive() or ctx['pid'] != self.proc.pid))", "False"),
         ('agent_browser.py', "        if ctx.get('window_id') is not None and ctx['window_id'] != seen[0]:\n            raise not_ours", "        if False:\n            raise not_ours")],
        ['test_resize.Refusals.test_the_users_window_is_never_resized', 'test_resize.Refusals.test_another_window_id_in_the_agent_process_is_not_resized']),
    'resize_accepted_without_readback': (
        'call a delivered set_window_frame done without the Driver\'s confirmed readback (#78)',
        [('agent_browser.py', "        if value.get('effect') != 'confirmed' or not (read_back or readback) or (readback and not self._close(readback, target)):", "        if False:")],
        ['test_resize.NotProven.test_an_effect_that_is_not_confirmed_is_not_done', 'test_resize.NotProven.test_a_confirmed_effect_without_a_readback_is_not_done',
         'test_resize.NotProven.test_a_readback_off_by_more_than_two_points_is_not_done']),
    'resize_lets_the_window_leave_the_display': (
        'no clamp and no whole-window-inside re-check (#78)',
        [('agent_browser.py', "        w, h = min(width, area['width']), min(height, area['height'])", "        w, h = width, height"),
         ('agent_browser.py', "        x = min(max(before['x'], area['x']), area['x'] + area['width'] - w)", "        x = before['x']"),
         ('agent_browser.py', "        y = min(max(before['y'], area['y']), area['y'] + area['height'] - h)", "        y = before['y']"),
         ('agent_browser.py', " or not f.agent.inside(now):", ":")],
        ['test_resize.Resize.test_a_resize_larger_than_the_display_is_clamped_and_the_window_stays_inside', 'test_resize.Resize.test_a_window_near_the_edge_is_moved_in_not_left_sticking_out',
         'test_resize.NotProven.test_a_window_that_ends_outside_the_display_is_refused_even_with_a_matching_readback']),
    'resize_keeps_the_stale_look': (
        'leave the cached look of the resized window in place (#78)',
        [('agent_browser.py', "            del f.looks[key]", "            pass")],
        ['test_resize.Resize.test_the_next_look_does_not_bind_to_a_look_taken_before_the_resize']),
    'hash_only_the_displayed_lines': (
        'the look_id covers what was displayed, not the full lines (review P1-1)',
        [('look.py', "return look_id_of([r['rec']['lines'] for r in rows], title, analysis['headings'], analysis['control_state'])", "return look_id_of([r['lines'] for r in rows], title, analysis['headings'], analysis['control_state'])")],
        ['test_plan_review.HiddenText.test_a_change_hidden_past_the_cut_after_the_look_invalidates_the_look_id', 'test_plan_review.HiddenText.test_the_look_id_changes_when_hidden_text_changes']),
    'negative_conditions_over_cut_lines_allowed': (
        'evaluate not_contains and neq on the displayed (cut) lines (review P1-1)',
        [('plan.py', "        if hidden:\n            return", "        if False:\n            return")],
        ['test_plan_review.HiddenText.test_a_negative_condition_over_a_cut_line_is_refused_and_clicks_nothing', 'test_plan_review.HiddenText.test_neq_over_a_cut_line_is_refused_too',
         'test_plan_review.HiddenText.test_lines_omitted_beyond_six_count_as_hidden_text']),
    'identity_matched_by_substring': (
        'the identity is present as a substring (review P1-2)',
        [('plan.py', "    return bool(w) and re.search(", "    return bool(w) and w in text or re.search(")],
        ['test_plan_review.Identity.test_an_identity_that_is_only_a_prefix_of_another_number_is_not_a_match', 'test_plan_review.Identity.test_the_identity_unit_rules']),
    'destructive_unlocked_by_goal_text': (
        'a regex over the goal unlocks a destructive control (review P1-3)',
        [('plan.py', "            if bad and not allowed(step.get('allow_destructive'), label):", "            if bad and not (allowed(step.get('allow_destructive'), label) or re.search(r'delet|remov|eras|discard|reset|sign out', lk.norm(goal))):"),
         ('core.py', "                if bad and not planmod.allowed(plan.get('allow'), action.get('name') or ''):", "                if bad and not (planmod.allowed(plan.get('allow'), action.get('name') or '') or re.search(r'delet|remov|eras|discard|reset|sign out', plan['goal'].casefold())):")],
        ['test_plan_review.Destructive.test_a_negated_goal_never_unlocks_a_destructive_control', 'test_plan_review.Destructive.test_a_goal_that_says_delete_still_needs_the_declaration']),
    'any_declaration_unlocks': (
        'allow_destructive of any text unlocks the control (review P1-3)',
        [('plan.py', "    return bool(step_allow) and lk.fold(step_allow) == lk.fold(label)", "    return bool(step_allow)")],
        ['test_plan_review.Destructive.test_a_declaration_for_another_label_does_not_allow_it']),
    'prefix_control_in_plans': (
        'reuse the whole-word prefix in plans: Finish presses Finish later (review P2-5)',
        [('plan.py', "        f.prefix_control = step.get('control_match') == 'prefix'", "        f.prefix_control = True")],
        ['test_plan_review.ExactControl.test_finish_does_not_click_finish_later']),
    'page_identity_ignored': (
        'a look_id over the record lines only (review P2-4)',
        [('look.py', "json.dumps([title or '', list(headings), full_lines, list(controls)], ensure_ascii=False, default=str)", "json.dumps([full_lines, list(controls)], ensure_ascii=False, default=str)")],
        ['test_plan_review.PageIdentity.test_a_different_heading_over_the_same_rows_is_a_different_page']),
    'looks_keyed_by_hash_alone': (
        'the second look of identical rows overwrites the first (review P2-4)',
        [('look.py', "f.looks[(pid, window_id, response['look_id'])] =", "f.looks[(None, None, response['look_id'])] ="),
         ('core.py', "                lines_where['look'] = self.looks.get((ctx['pid'], ctx['window_id'], lines_where['look_id']))", "                lines_where['look'] = self.looks.get((None, None, lines_where['look_id']))\n                if lines_where['look'] and (lines_where['look']['pid'], lines_where['look']['window_id']) != (ctx['pid'], ctx['window_id']):lines_where['look'] = None")],
        ['test_plan_review.TwoWindows.test_identical_rows_in_two_windows_do_not_overwrite_each_others_look']),
    'page_text_unmarked': (
        'return page text with no untrusted marker (review P3-6)',
        [('look.py', "'untrusted_page_text': True, 'notice': NOTICE, ", ""), ('core.py', "            result['untrusted_page_text'] = True  # the flag is on every response; the fixed sentence only where it is news (CE-FACADE-011)\n            if self._notice_needed(result):result['notice'] = lookmod.NOTICE\n            else:result.pop('notice', None)", "            pass")],
        ['test_plan_review.UntrustedText.test_every_look_says_the_page_text_is_untrusted_data']),
    'child_map_cached_on_the_facade': (
        'cache the subtree child map across observations (review P3-7)',
        [('core.py', "        kids = state.get('_kids')\n        if kids is None:", "        kids = getattr(self, '_kidcache', None)\n        if kids is None:"),
         ('core.py', "            state['_kids'] = kids\n", "            self._kidcache = kids\n")],
        ['test_plan_review.SubtreeCache.test_a_new_observation_never_reuses_an_old_child_map']),
    'claim_worded_as_a_fact': (
        'a result line saying the deterministic look is good enough (review P3-8)',
        [('../scripts/look_compare.py', "sufficiency of the deterministic look is UNMEASURED live.", "the deterministic look is good enough on a 100-row page.")],
        ['test_plan_review.Wording.test_no_heading_or_result_line_states_the_claim_as_a_fact']),
    'uniqueness_over_the_displayed_records_only': (
        'SHRINK visible->all: only the displayed records are candidates (second review P1-A)',
        [('plan.py', "    visible = {r['rec']['root']: r for r in every}  # ALL records: uniqueness is a property of the page, not of the look", "    visible = {r['rec']['root']: r for r in rows_look}")],
        ['test_plan_review2.UniquenessOverAllRecords.test_a_capped_look_cannot_turn_an_ambiguous_condition_into_a_click', 'test_plan_review2.UniquenessOverAllRecords.test_a_focused_look_cannot_either', 'test_plan_review2.UniquenessOverAllRecords.test_on_the_booking_page_a_focus_on_one_slot_still_counts_the_others']),
    'confirm_whitelist_off': (
        'the dialog text is not compared with the declaration (second review P1-B/C)',
        [('core.py', "            if {norm(x) for x in cs['dialog_text']} != {norm(x) for x in actual_lines} or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:", '            if False:')],
        ['test_plan_review2.ConfirmWhitelist.test_an_extra_line_the_caller_did_not_declare_defers_and_shows_the_actual_lines', 'test_plan_review2.ConfirmWhitelist.test_any_different_line_defers_whatever_the_language_or_verb', 'test_plan_review2.ConfirmWhitelist.test_a_declared_line_that_is_missing_defers']),
    'whitelist_allows_extra_actual_lines': (
        'the declared lines only need to be present (subset check): "Do not proceed" on the next line passes',
        [('core.py', "            if {norm(x) for x in cs['dialog_text']} != {norm(x) for x in actual_lines} or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:", "            if not {norm(x) for x in cs['dialog_text']} <= {norm(x) for x in actual_lines} or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:")],
        ['test_plan_review2.ConfirmWhitelist.test_an_extra_line_the_caller_did_not_declare_defers_and_shows_the_actual_lines']),
    'whitelist_allows_missing_declared_lines': (
        'every actual line is declared but declared lines may be absent',
        [('core.py', "            if {norm(x) for x in cs['dialog_text']} != {norm(x) for x in actual_lines} or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:", "            if not {norm(x) for x in actual_lines} <= {norm(x) for x in cs['dialog_text']} or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:")],
        ['test_plan_review2.ConfirmWhitelist.test_a_declared_line_that_is_missing_defers']),
    'dialog_text_optional': (
        'a confirm step without dialog_text is accepted (judged by nothing)',
        [('plan.py', '            if not isinstance(declared, list) or not declared or not all(isinstance(x, str) and x.strip() for x in declared) or len(declared) > 20:', '            declared = declared or []\n            if False:'), ('plan.py', "'dialog_text': step['dialog_text'],", "'dialog_text': step.get('dialog_text') or [],")],
        ['test_plan_review2.ConfirmWhitelist.test_a_confirm_step_must_declare_the_dialog_text']),
    'destructive_list_shrunk_wipe': (
        'SHRINK: the wipe stem is dropped from the destructive list',
        [('plan.py', 'wip(?:e|ing)', 'wip(?:e|ing)XX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_unsubscribe': (
        'SHRINK: the unsubscribe stem is dropped from the destructive list',
        [('plan.py', 'bunsubscrib', 'bunsubscribXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_clear': (
        'SHRINK: the clear stem is dropped from the destructive list',
        [('plan.py', 'bclear', 'bclearXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_overwrite': (
        'SHRINK: the overwrite stem is dropped from the destructive list',
        [('plan.py', 'boverwrit', 'boverwritXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_deactivate': (
        'SHRINK: the deactivate stem is dropped from the destructive list',
        [('plan.py', 'bdeactivat', 'bdeactivatXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_terminate': (
        'SHRINK: the terminate stem is dropped from the destructive list',
        [('plan.py', 'bterminat', 'bterminatXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_revoke': (
        'SHRINK: the revoke stem is dropped from the destructive list',
        [('plan.py', 'brevok', 'brevokXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_disconnect': (
        'SHRINK: the disconnect stem is dropped from the destructive list',
        [('plan.py', 'bdisconnect', 'bdisconnectXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_purge': (
        'SHRINK: the purge stem is dropped from the destructive list',
        [('plan.py', 'bpurg', 'bpurgXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_destroy': (
        'SHRINK: the destroy stem is dropped from the destructive list',
        [('plan.py', 'bdestroy', 'bdestroyXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_uninstall': (
        'SHRINK: the uninstall stem is dropped from the destructive list',
        [('plan.py', 'buninstall', 'buninstallXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_log_out': (
        'SHRINK: the log out stem is dropped from the destructive list',
        [('plan.py', 'log(?:ging|ged)?[ -]?out', 'log(?:ging|ged)?[ -]?outXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_close_account': (
        'SHRINK: the close account stem is dropped from the destructive list',
        [('plan.py', "close account': r'", "close account': r'XX")],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_delete': (
        'SHRINK: the delete stem is dropped from the destructive list',
        [('plan.py', 'bdelet', 'bdeletXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_remove': (
        'SHRINK: the remove stem is dropped from the destructive list',
        [('plan.py', 'bremov', 'bremovXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_erase': (
        'SHRINK: the erase stem is dropped from the destructive list',
        [('plan.py', 'beras', 'berasXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_discard': (
        'SHRINK: the discard stem is dropped from the destructive list',
        [('plan.py', 'bdiscard', 'bdiscardXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'destructive_list_shrunk_reset': (
        'SHRINK: the reset stem is dropped from the destructive list',
        [('plan.py', 'breset', 'bresetXX')],
        ['test_plan_review2.WidenedVerbs.test_every_listed_verb_needs_the_declaration_before_any_click']),
    'boundary_shrunk_hash': (
        'SHRINK: # dropped from the token boundary characters',
        [('plan.py', '(?<![a-z0-9#_.,-])', '(?<![a-z0-9_.,-])')],
        ['test_plan_review.Identity.test_the_identity_unit_rules']),
    'boundary_shrunk_underscore': (
        'SHRINK: _ dropped from the token boundary characters',
        [('plan.py', '(?![a-z0-9#_-])', '(?![a-z0-9#-])')],
        ['test_plan_review2.ConfirmWhitelist.test_identity_lookalikes_are_not_tokens_even_when_declared']),
    'boundary_shrunk_hyphen': (
        'SHRINK: - dropped from the token boundary characters',
        [('plan.py', '(?![a-z0-9#_-])', '(?![a-z0-9#_])')],
        ['test_plan_review2.ConfirmWhitelist.test_identity_lookalikes_are_not_tokens_even_when_declared']),
    'boundary_shrunk_decimal': (
        'SHRINK: a following .5 or ,5 no longer breaks the token',
        [('plan.py', '(?![.,]', '(?!zz')],
        ['test_plan_review2.ConfirmWhitelist.test_identity_lookalikes_are_not_tokens_even_when_declared']),
    'boundary_shrunk_alnum_after': (
        'SHRINK: letters and digits after the token no longer break it',
        [('plan.py', '(?![a-z0-9#_-])', '(?![#_-])')],
        ['test_plan_review2.ConfirmWhitelist.test_identity_lookalikes_are_not_tokens_even_when_declared', 'test_plan_review.Identity.test_the_identity_unit_rules']),
    'hidden_text_selection_unacknowledged': (
        'a record with cut or omitted lines is selected without accept_hidden_text (second review P2-A)',
        [('plan.py', "    if visible[int(only[1:])]['lost'] and not spec.get('accept_hidden'):", '    if False:')],
        ['test_plan_review2.HiddenTextAcknowledgement.test_selecting_a_record_with_hidden_lines_defers_unless_acknowledged']),
    'look_line_options_ignored': (
        'max_lines and line_chars accepted and ignored',
        [('look.py', "        shown, lost = display_lines(rec['lines'], opts)", "        shown, lost = display_lines(rec['lines'])")],
        ['test_plan_review2.HiddenTextAcknowledgement.test_a_look_that_shows_the_full_lines_needs_no_acknowledgement_and_can_use_negatives']),
    'control_state_not_hashed': (
        'the look_id ignores every control state (second review P2-B)',
        [('look.py', 'list(headings), full_lines, list(controls)]', 'list(headings), full_lines, []]')],
        ['test_plan_review2.ControlState.test_a_checkbox_flipped_between_look_and_plan_is_a_different_page', 'test_plan_review2.ControlState.test_a_control_enabled_state_or_value_change_invalidates_the_look']),
    'toggle_pressed_without_a_look': (
        'a checkbox is pressed with no look that saw its state',
        [('core.py', "why = 'toggle_state_unseen' if seen is None else", 'why = None if seen is None else')],
        ['test_plan_review2.ControlState.test_an_unchanged_checkbox_presses_and_a_toggle_without_a_look_is_not_pressed_blind']),
    'responses_unmarked': (
        'do responses carry page text without the untrusted marker (second review P2-C)',
        [('core.py', "            result['untrusted_page_text'] = True  # the flag is on every response; the fixed sentence only where it is news (CE-FACADE-011)\n            if self._notice_needed(result):result['notice'] = lookmod.NOTICE\n            else:result.pop('notice', None)", '            pass')],
        ['test_plan_review2.UntrustedEverywhere.test_plan_responses_carry_the_marker_in_every_page_text_field', 'test_plan_review2.UntrustedEverywhere.test_single_step_responses_carry_the_marker_and_no_page_text_in_hints']),
    'page_text_in_a_hint': (
        'a control label is put into a hint (second review P2-C)',
        [('core.py', "'control_needed': 'Each record has several controls (found.repeated_controls lists their labels). Call do again with control=<the exact label of the one to press>.',", "'control_needed': 'Each record has several controls (%s). Call do again with control=<the exact label of the one to press>.' % ', '.join(c['label'] for c in found['repeated_controls']),")],
        ['test_plan_review2.UntrustedEverywhere.test_single_step_responses_carry_the_marker_and_no_page_text_in_hints']),
    'region_compares_static_text_only': (
        'the dialog whitelist compares only static texts and headings (third review P1-1)',
        [('look.py', "        line, dropped = node_line(n)\n        if dropped:line = 'text: '", "        line, dropped = (text_of(n) if n.get('role') in ('AXStaticText', 'AXHeading') else None), False\n        if dropped:line = 'text: '")],
        ['test_plan_review3.DialogRegion.test_extra_text_in_an_image_node_inside_the_dialog_defers', 'test_plan_review3.DialogRegion.test_extra_text_in_a_group_label_or_description_defers', 'test_plan_review3.DialogRegion.test_extra_text_in_a_text_area_value_defers', 'test_plan_review3.DialogRegion.test_a_prefilled_text_field_defers_and_declaring_it_authorizes_it']),
    'dialog_controls_not_compared': (
        'declared dialog_controls are not compared with the actual controls',
        [('core.py', " or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:", ':')],
        ['test_plan_review3.DialogRegion.test_an_extra_button_next_to_the_declared_ones_defers', 'test_plan_review3.DialogRegion.test_an_extra_link_defers_too']),
    'control_state_marker_dropped': (
        'SHRINK: a control state ([checked]) is not part of its declared item',
        [('look.py', "    if marker in ('checked', 'selected'):item += ' [%s]' % marker", '    pass')],
        ['test_plan_review3.DialogRegion.test_a_prechecked_checkbox_defers_with_its_state_and_declaring_the_state_authorizes_it']),
    'region_only_new_nodes_in_content': (
        'SHRINK: new nodes outside the web area are ignored',
        [('core.py', "            if i in content or (not chrome(i) and nodes[i].get('role') not in ('AXTextField', 'AXComboBox', 'AXSearchField')):new.append(i)", '            if i in content:new.append(i)')],
        ['test_plan_review3.DialogRegion.test_a_warning_parented_outside_the_cluster_defers']),
    'region_without_container': (
        'SHRINK: the container holding the dialog cluster is not compared (already-present text dropped)',
        [('core.py', "            if parent in nodes and nodes[parent].get('role') not in ('AXWebArea', 'AXWindow'):region |= below(parent)", '            if False:region |= below(parent)')],
        ['test_plan_review3.DialogRegion.test_text_already_on_the_page_inside_the_dialog_container_is_still_compared']),
    'dialog_controls_optional': (
        'dialog_controls accepted as absent',
        [('plan.py', '            if not isinstance(controls, list) or not controls or not all(isinstance(x, str) and x.strip() for x in controls) or len(controls) > 20:', "            controls = controls or list(step.get('dialog_controls') or [step.get('confirm')])\n            step['dialog_controls'] = controls\n            if False:")],
        ['test_plan_review3.DialogRegion.test_dialog_controls_are_required_and_the_confirm_label_must_be_among_them']),
    'record_lines_text_only': (
        'record lines drop image, group, field and state text (third review P1-2)',
        [('look.py', '                lines, dropped = tagged_under(members, root)', '                lines, dropped = texts_under(members), 0')],
        ['test_plan_review3.RecordText.test_an_image_label_inside_a_record_is_a_tagged_line', 'test_plan_review3.RecordText.test_a_negative_condition_sees_the_image_badge']),
    'unrepresentable_text_not_counted_hidden': (
        'a text-bearing container the look cannot show is silently dropped',
        [('look.py', '                if drop and i != root:dropped += 1', '                pass')],
        ['test_plan_review3.RecordText.test_a_text_bearing_node_the_look_cannot_represent_counts_as_hidden']),
    'look_id_by_element_index': (
        'SHRINK: the state hash is keyed by element index, not structural path (third review P2-3)',
        [('look.py', "        return [path(i)] + [str(n.get(k))", "        return [str(i)] + [str(n.get(k))")],
        ['test_plan_review3.LookIdStructure.test_a_banner_before_the_list_does_not_change_the_id_but_an_input_value_does', 'test_plan_review3.LookIdStructure.test_a_banner_before_the_list_still_lets_a_plan_proceed']),
    'input_value_not_hashed': (
        'SHRINK: the value is dropped from the hashed control state',
        [('look.py', "CONTROL_STATE_KEYS = ('role', 'label', 'value', ", "CONTROL_STATE_KEYS = ('role', 'label', ")],
        ['test_plan_review3.LookIdStructure.test_a_page_level_input_value_or_chosen_option_is_in_the_id']),
    'aria_state_keys_shrunk': (
        'SHRINK: current and busy dropped from the hashed state keys',
        [('look.py', "'pressed', 'current', 'busy')  # whatever", "'pressed')  # whatever")],
        ['test_plan_review3.LookIdStructure.test_a_current_or_busy_state_exposed_by_the_observation_is_in_the_id']),
    'look_marker_only_on_ok': (
        'the untrusted marker is applied only inside the ok path',
        [('core.py', '        with self.lock:return self.mark(lookmod.run_look(', '        with self.lock:return (lookmod.run_look(')],
        ['test_plan_review3.MarkerOnEveryPath.test_every_look_path_carries_the_marker']),
    'driver_failure_message_raw': (
        'the single-step driver failure echoes str(gap)',
        [('core.py', "message='driver_call_failed: a Driver call failed; delivery and retryable say whether anything may have been clicked', detail=self._failure_detail(gap), attempts=", 'message=str(gap), detail=self._failure_detail(gap), attempts=')],
        ['test_plan_review3.MarkerOnEveryPath.test_every_do_path_carries_the_marker_and_no_message_is_raw']),
    'fold_homoglyphs_dropped': (
        'SHRINK: Cyrillic/Greek look-alikes are not mapped',
        [('look.py', '_HOMOGLYPHS.get(c, c)', 'c')],
        ['test_plan_review3.DestructiveFold.test_look_alike_and_invisible_characters_are_folded_before_matching']),
    'fold_zero_width_kept': (
        'SHRINK: zero-width characters are not stripped (replaced by a letter instead)',
        [('look.py', "\\ufeff\\u00ad]', '', t)", "\\ufeff\\u00ad]', 'x', t)")],
        ['test_plan_review3.DestructiveFold.test_look_alike_and_invisible_characters_are_folded_before_matching']),
    'fold_diacritics_kept': (
        'SHRINK: diacritics are not dropped',
        [('look.py', "unicodedata.category(c) != 'Mn'", 'True')],
        ['test_plan_review3.DestructiveFold.test_look_alike_and_invisible_characters_are_folded_before_matching']),
    'fold_nfkc_dropped': (
        'SHRINK: no NFKC (fullwidth letters, non-breaking spaces survive)',
        [('look.py', "    t = unicodedata.normalize('NFKC', str(text or ''))", "    t = str(text or '')"), ('look.py', "unicodedata.normalize('NFKD', t)", "unicodedata.normalize('NFD', t)")],
        ['test_plan_review3.DestructiveFold.test_look_alike_and_invisible_characters_are_folded_before_matching']),
    'destructive_list_shrunk_buy': (
        'SHRINK: the buy stem is dropped from the irreversible/outward list',
        [('plan.py', 'buy(?:ing)?', 'buyXX(?:ing)?')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_purchase': (
        'SHRINK: the purchase stem is dropped from the irreversible/outward list',
        [('plan.py', 'bpurchas', 'bpurchasXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_pay': (
        'SHRINK: the pay stem is dropped from the irreversible/outward list',
        [('plan.py', 'pay(?:ing)?', 'payXX(?:ing)?')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_send': (
        'SHRINK: the send stem is dropped from the irreversible/outward list',
        [('plan.py', 'send(?:ing)?', 'sendXX(?:ing)?')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_publish': (
        'SHRINK: the publish stem is dropped from the irreversible/outward list',
        [('plan.py', 'bpublish', 'bpublishXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_transfer': (
        'SHRINK: the transfer stem is dropped from the irreversible/outward list',
        [('plan.py', 'btransfer', 'btransferXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_refund': (
        'SHRINK: the refund stem is dropped from the irreversible/outward list',
        [('plan.py', 'brefund', 'brefundXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_void': (
        'SHRINK: the void stem is dropped from the irreversible/outward list',
        [('plan.py', 'bvoid', 'bvoidXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_submit_order': (
        'SHRINK: the submit order stem is dropped from the irreversible/outward list',
        [('plan.py', 'bsubmit', 'bsubmitXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_place_order': (
        'SHRINK: the place order stem is dropped from the irreversible/outward list',
        [('plan.py', 'bplace', 'bplaceXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'destructive_list_shrunk_confirm_payment': (
        'SHRINK: the confirm payment stem is dropped from the irreversible/outward list',
        [('plan.py', 'bconfirm', 'bconfirmXX')],
        ['test_plan_review3.DestructiveFold.test_irreversible_and_outward_verbs_need_the_declaration']),
    'whole_word_stems_widened': (
        'SHRINK: disconnect and remove match as prefixes again (Disconnected, Removed items)',
        [('plan.py', 'disconnect(?:s|ing)?\\b', 'disconnect\\w*'), ('plan.py', 'remov(?:e|es|ing)\\b', 'remov\\w*')],
        ['test_plan_review3.DestructiveFold.test_documented_false_positives_stay_and_whole_word_stems_do_not_overmatch']),
    'heading_value_read_as_text': (
        'a heading value (its LEVEL) is read as text (live capture D1/D3)',
        [('look.py', "    for key in (('label',) if node.get('role') == 'AXHeading' else ('value', 'label')):", "    for key in ('value', 'label'):")],
        ['test_real_pages.RecordPages.test_the_page_text_has_no_heading_level_numerals', 'test_real_pages.RecordPages.test_nested_records_have_no_level_numerals_and_keep_the_section_headings']),
    'subtree_reads_heading_level': (
        'the shared subtree text reads a heading value (do/D record text)',
        [('core.py', "                for key in (('label',) if n.get('role') == 'AXHeading' else ('label','value')):", "                for key in ('label','value'):")],
        ['test_real_pages.RecordPages.test_do_record_context_of_nested_has_no_heading_level_numerals']),
    'title_heading_glued_to_the_first_record': (
        'SHRINK: the page title is never recognized as page text',
        [('core.py', '        if not title or not n:return False', '        return False')],
        ['test_real_pages.RecordPages.test_flat_ax_first_record_carries_neither_the_heading_nor_its_level', 'test_real_pages.RecordPages.test_do_record_context_agrees_with_the_look', 'test_real_pages.RecordPages.test_a_where_lines_plan_cannot_select_the_first_flat_record_by_the_page_title']),
    'sibling_record_keeps_the_title': (
        'sibling_record no longer skips the title heading',
        [('core.py', "        members = [i for i in members if not self._title_member(state, i)]  # the page's own title heading is page text, not the first record's", '        members = members')],
        ['test_real_pages.RecordPages.test_do_record_context_agrees_with_the_look']),
    'selected_false_is_a_state': (
        'selected:false on a plain button is emitted as [unselected] noise (live capture D2)',
        [('look.py', "    return 'selected' if n.get('selected') is True else None", "    return 'selected' if n.get('selected') is True else ('unselected' if 'selected' in n else None)")],
        ['test_real_pages.RecordPages.test_plain_buttons_add_no_state_noise_to_any_record', 'test_real_pages.InputPages.test_toggle_marker_unit']),
    'radio_value_ignored': (
        'SHRINK: a radio or checkbox state is not read from value 0/1',
        [('look.py', " or str(n.get('value')).strip().lower() in ('1', 'true', 'on', 'checked')", ' or False')],
        ['test_real_pages.InputPages.test_wizard_radios_read_their_state_from_value_and_selected', 'test_real_pages.InputPages.test_toggle_marker_unit']),
    'radio_selected_ignored': (
        'SHRINK: a radio state is not read from selected',
        [('look.py', "n.get('checked') is True or n.get('selected') is True or", "n.get('checked') is True or")],
        ['test_real_pages.InputPages.test_wizard_radios_read_their_state_from_value_and_selected', 'test_real_pages.InputPages.test_toggle_marker_unit']),
    'look_id_hashes_selected_false': (
        'the look_id hashes falsy state flags (Chrome selected:false on every button)',
        [('look.py', "if (k in ('role', 'label', 'value', 'enabled') or n.get(k)) else ''", "if True else ''")],
        ['test_real_pages.RecordPages.test_look_id_ignores_selected_false_noise_but_sees_real_state']),
    'page_toggles_not_shown': (
        'the look does not list page-level toggle states',
        [('look.py', "                **({'toggles': analysis['toggles'][:INPUT_LIST_MAX]} if analysis['toggles'] else {}),", '')],
        ['test_real_pages.InputPages.test_wizard_radios_read_their_state_from_value_and_selected']),
    'max_bytes_underestimated': (
        'max_bytes bounds an estimate, not the response (live capture: 6015 > 6000 on invoices)',
        [('look.py', '        return len(json.dumps(out))\n    keep = len(encoded)', '        return len(json.dumps(out)) - 3000\n    keep = len(encoded)')],
        ['test_real_pages.RecordPages.test_invoices_reports_the_byte_cap_and_does_not_silently_drop']),
    'budget_look_reader': (
        'the default look reads through NuExtract (measured through the real server tools)',
        [('look.py', "        f.looks[(pid, window_id, response['look_id'])] = {", "        try:f.provider('reader').extract({'snapshot_id': state['raw']['snapshot_id'], 'task': 't', 'fields': {'x': 'x'}, 'records': [{'id': 'e1', 'text': 't'}]}, state['raw']['snapshot_id'])\n        except Exception:pass  # the fake reader counts the request before it looks for a pattern\n        f.looks[(pid, window_id, response['look_id'])] = {")],
        ['test_budget.DefaultPathBudget.test_look_then_plan_is_two_calls_with_no_reader_and_no_chooser_on_the_real_trees']),
    # CE-FACADE-007 wave 3 (#33, #34, #39)
    'semantic_call_unbounded': (
        'wait for the semantic snapshot with the Driver default timeout (#29 ran 120 s with no output)',
        [('dom.py', "        value = f.driver.call('get_browser_state', {'session': f.session, **args}, timeout=timeout)", "        value = f.driver.call('get_browser_state', {'session': f.session, **args})")],
        ['test_dom.Bounded.test_a_hanging_semantic_call_is_bounded_and_the_look_falls_back_to_ax']),
    'dom_replaces_ax_silently': (
        'prefer the DOM silently: its lines replace the AX lines of a record',
        [('look.py', "            r['dom_lines'] = shown", "            r['dom_lines'] = shown;r['rec'] = dict(r['rec'], lines=lines);r['lines'] = shown")],
        ['test_dom.Sources.test_the_dom_never_replaces_or_drops_the_ax_look']),
    'ax_dropped_when_dom_present': (
        'drop the AX records when a DOM snapshot is present',
        [('look.py', "    found = dom.compare(analysis, semantic, dom.ax_text_blob(f, state, analysis))", "    found = dom.compare(analysis, semantic, dom.ax_text_blob(f, state, analysis));rows[:] = []")],
        ['test_dom.Sources.test_the_dom_never_replaces_or_drops_the_ax_look']),
    'read_pages_failure_skips_the_rest': (
        'a page that does not land ends the multi-page read for the other pages',
        [('browser.py', "            if reason in STOP_ALL:\n                stop = reason", "            stop = reason")],
        ['test_read_pages.Reads.test_a_page_that_lands_elsewhere_does_not_abort_the_others_silently']),
    'menu_reroute_on_any_refusal': (
        'route every failure of the ordinary menu press through invoke_menu',
        [('menu.py', "        refused = getattr(gap, 'code', None) == REFUSAL if isinstance(gap, DriverCallFailed) else REFUSAL in str(gap)", "        refused = True")],
        ['test_menu.Routing.test_any_other_refusal_of_a_menu_item_is_not_rerouted', 'test_menu.Routing.test_another_exit_1_code_is_never_rerouted']),
    'menu_reroute_without_foreground': (
        "invoke_menu (which activates the window) without the caller's allow_foreground",
        [('menu.py', "        if not f.foreground_ok:\n            raise _gap('%s: the Driver refused to press", "        if False:\n            raise _gap('%s: the Driver refused to press")],
        ['test_menu.Routing.test_the_refusal_is_preserved_without_allow_foreground_because_invoke_menu_fronts_the_window']),
    # CE-FACADE-008 (#54): a device is look, then do through mobile-mcp. Each wrong patch below is a tempting shortcut of that contract.
    'device_tap_on_the_looks_stale_list': (
        'reuse the element list the look read (cheaper): after any layout change the ref or bounds point at another control',
        [('mobile.py', "        return parse_elements(text)\n", "        return self.__dict__.setdefault('_stale', {}).setdefault(device, parse_elements(text))\n")],
        ['test_mobile.DoPress.test_a_press_taps_the_fresh_element_not_what_the_look_showed', 'test_mobile.DoPress.test_a_two_step_plan_reads_fresh_for_every_step']),
    'device_first_of_several_matches': (
        'tap the first of several elements that carry the label instead of refusing',
        [('mobile.py', "        if len(ok) == 1:\n            return ok[0], None", "        if ok:\n            return ok[0], None")],
        ['test_mobile.DoPress.test_several_matching_elements_are_never_guessed']),
    'device_trust_the_taps_ok': (
        "call a tap done because mobile-mcp answered \"Clicked on\" (a locked phone drops taps silently: upstream found exactly that)",
        [('mobile.py', "    return x.settle(step, before, TAP_DELAYS, extra={'selected': selected})", "    return {'status': 'done', 'delivery': 'delivered', 'selected': selected}")],
        ['test_mobile.DoPress.test_a_tap_the_device_did_not_act_on_is_never_done',
         'test_mobile.DoPress.test_a_tap_that_changed_the_screen_but_not_as_expected_is_unverified_not_done',
         'test_mobile.DoPress.test_no_expect_on_the_last_step_ends_delivered_unverified_never_done']),
    'device_missing_node_crashes': (
        'skip the Node.js check and let the spawn failure speak (no install instruction, a start attempted)',
        [('mobile.py', "        if self.which(exe) is None:\n            if exe == 'npx':", "        if False:\n            if exe == 'npx':")],
        ['test_mobile.Lifecycle.test_without_node_the_answer_is_a_typed_refusal_naming_what_to_install']),
    'device_action_resent_after_the_child_died': (
        'retry the tap on the restarted mobile-mcp (it may already have landed)',
        [('mobile.py', "                if mutating:\n                    raise MobileGap('mobile_action_failed', 'the mobile-mcp process exited during the action", "                if False:\n                    raise MobileGap('mobile_action_failed', 'the mobile-mcp process exited during the action")],
        ['test_mobile.Lifecycle.test_an_action_is_never_re_sent_when_the_child_dies_under_it']),
    'device_type_without_checking_the_focus': (
        'type after the tap without looking where the focus went (a dropped tap leaves it on the other field)',
        [('mobile.py', "    if (mine is None or not mine['focused']) and others:", "    if False:")],
        ['test_mobile.DoType.test_nothing_is_typed_when_the_focus_is_on_another_field']),
    'device_destructive_guard_on_the_literal_label_only': (
        'check only the label the caller wrote, not the names of the element it resolved to',
        [('mobile.py', "    for name in list(element['names']) + [literal]:", "    for name in [literal]:")],
        ['test_mobile.DoPress.test_a_control_that_only_resolves_to_a_destructive_element_is_not_pressed']),
    'device_raw_backend_text_in_the_answer': (
        "return mobile-mcp's own error text to the model (a local path and a stack)",
        [('mobile.py', "        reason, message, delivery = classify(text)\n        raise MobileGap(reason, message, delivery)", "        reason, message, delivery = classify(text)\n        raise MobileGap(reason, message + ' ' + str(text), delivery)")],
        ['test_mobile.LookOnDevices.test_raw_backend_text_never_reaches_the_answer']),
    'device_look_truncates_silently': (
        'cut the device look to max_bytes and report nothing cut',
        [('mobile.py', "        response['truncated'] = {'records': matched - len(rows), 'lines': lost, 'bytes': bytes_cut}", "        response['truncated'] = {'records': 0, 'lines': 0, 'bytes': 0}")],
        ['test_mobile.LookOnDevices.test_bounds_are_reported_never_silent']),
    'device_typed_text_proves_itself': (
        'accept the text just typed as the proof that typing worked (it is in the field either way)',
        [('mobile.py', "    if typed is not None and (needle in lk.norm(typed) or lk.norm(typed) in needle):", "    if False:")],
        ['test_mobile.DoType.test_the_text_just_typed_never_proves_itself']),
    'device_close_leaves_the_child_running': (
        'never stop mobile-mcp when the server shuts down',
        [('mobile.py', "        with self._lock:\n            self._teardown()\n\n    # -- calls", "        pass\n\n    # -- calls")],
        ['test_mobile.Lifecycle.test_close_stops_the_child_and_the_next_call_starts_a_fresh_one']),
    # CE-FACADE-010 (#64): agent onboarding.
    'onboarding_setup_is_the_whole_doctor_report': (
        'attach every doctor check to a refusal instead of the ones that explain it',
        [('onboarding.py', "    names, fallback = BLOCKERS[reason]\n", "    names, fallback = tuple(c.__name__ for c in cli.STATIC_CHECKS), None\n")],
        ['test_onboarding.SetupBlock.test_a_browser_refusal_carries_only_the_browser_blockers_with_who',
         'test_onboarding.SetupBlock.test_a_device_refusal_carries_the_device_blocker_never_the_browser_ones']),
    'onboarding_setup_repeated_every_time': (
        'show the setup block on every refusal, not once per blocker set',
        [('onboarding.py', "    if not entries or key in f.setup_seen:", "    if not entries:")],
        ['test_onboarding.SetupBlock.test_once_per_blocker_set_and_again_when_the_set_changes']),
    'onboarding_setup_on_a_healthy_machine': (
        'list the checks that pass as blockers too',
        [('onboarding.py', "    found = [_entry(c) for name in names for c in _run(env, name) if c['status'] in (cli.WARN, cli.BLOCKER)]", "    found = [_entry(c) for name in names for c in _run(env, name)]")],
        ['test_onboarding.SetupBlock.test_never_on_a_healthy_machine']),
    'onboarding_doctor_runs_for_every_response': (
        'run the doctor checks whatever the refusal was',
        [('onboarding.py', "    hits = [r for r in reasons_of(result) if r in BLOCKERS]", "    hits = list(BLOCKERS)[:1]")],
        ['test_onboarding.SetupBlock.test_no_environment_reason_means_the_checks_are_never_run']),
    'onboarding_a_goto_is_the_aha_moment': (
        'count any done plan (a goto alone) as the first verified do',
        [('onboarding.py', "any(isinstance(s, dict) and s.get('do') in ACTIONS and s.get('status') == 'done' for s in steps)", "any(isinstance(s, dict) and s.get('status') == 'done' for s in steps)")],
        ['test_onboarding.FirstVerifiedDo.test_a_goto_or_a_verify_alone_is_not_the_aha_moment']),
    'onboarding_first_do_overwritten': (
        'overwrite time_to_first_verified_do on every done do',
        [('core.py', "if tool == 'do' and self.first_do is None and onboarding.is_verified_do(result):", "if tool == 'do' and onboarding.is_verified_do(result):")],
        ['test_onboarding.FirstVerifiedDo.test_it_is_recorded_once']),
    'onboarding_permission_refusal_gets_the_generic_hint': (
        'leave permission_required without its own hint (it falls to "call look to see the page")',
        [('plan.py', "    'permission_required': 'The Driver has no access", "    'permission_required_unused': 'The Driver has no access")],
        ['test_onboarding.HintCatalog.test_every_refusal_reason_that_reaches_a_response_has_its_own_hint',
         'test_onboarding.EmptyStates.test_the_no_permission_hint_names_who_and_the_retry_rule']),
    'onboarding_a_hint_that_restates_the_reason': (
        'a hint that only says what the reason already says',
        [('plan.py', "Call `look` and press another control, or tell the user the command is unavailable.'", "Report it.'")],
        ['test_onboarding.HintCatalog.test_every_hint_names_an_existing_tool_or_parameter_or_says_who_and_the_retry_rule']),
    'onboarding_empty_device_list_keeps_the_bare_hint': (
        'say only "pass device=<an id>" when there is no device to pass',
        [('mobile.py', "    elif not out['devices']:", "    elif False:")],
        ['test_onboarding.EmptyStates.test_no_devices_says_what_would_appear_and_the_one_call']),
    'onboarding_windows_notes_not_merged': (
        'compute the windows empty-state notes but return the bare list',
        [('server.py', "            found={**found,**onboarding.windows_notes(facade,found,title)}", "            found=found")],
        ['test_onboarding.EmptyStates.test_the_advanced_windows_tool_merges_the_notes']),
    'onboarding_title_dropped_for_every_plan': (
        'stop requiring a title for any plan, not only a goto on the agent browser',
        [('plan.py', "    first = steps[0] if isinstance(steps, list) and steps and isinstance(steps[0], dict) else {}\n", "    return True\n    first = {}\n")],
        ['test_onboarding.FirstCallNeedsNoTitle.test_everything_else_still_names_its_window']),
    'onboarding_probe_reports_ready_without_a_verified_do': (
        'doctor --probe calls the machine ready once the clicks were delivered',
        [('cli.py', "        if done.get('status') != 'done' or not facade.first_do:", "        if False:")],
        ['test_onboarding.Probe.test_an_unverified_press_is_not_ready']),
    # CE-FACADE-008 follow-up (#59): records on device screens and the iOS agent bootstrap.
    'device_every_element_is_a_record': (
        'make every element its own record (no banding): lines never sit with their controls, so a row cannot be picked by what it says',
        [('mobile.py', "        if bands and top < bands[-1]['bottom'] - BAND_SLACK:", "        if False:")],
        ['test_mobile.RecordsOnDevices.test_a_list_screen_yields_one_record_per_row_with_its_lines_and_controls']),
    'device_record_without_a_control': (
        'keep every band as a record: headings and status text become records nobody can press',
        [('mobile.py', "        if not controls:\n            continue\n        wrapped =", "        wrapped =")],
        ['test_mobile.RecordsOnDevices.test_a_row_without_a_control_is_not_a_record']),
    'device_where_lines_without_a_look_id': (
        'let where.lines match on a device without a look_id (a filter written without seeing the screen)',
        [('plan.py', "    if needs_look:\n        if look_id is None:", "    if needs_look:\n        if False:"),
         ('plan.py', "        if not any(key[2] == look_id for key in f.looks):", "        if False:"),
         ('plan.py', "    if look_id is not None and not any(key[2] == look_id for key in f.looks):", "    if False:")],
        ['test_mobile.RecordsOnDevices.test_where_lines_needs_a_look_id_and_one_of_this_device']),
    'device_where_lines_ignores_a_changed_screen': (
        'skip the look_id recomputation: the rows moved since the look and the tap lands in the row that is now there',
        [('mobile.py', "    if look_id_for(a, shown, x.device) != step['_look_id']:", "    if False:")],
        ['test_mobile.RecordsOnDevices.test_the_screen_must_still_read_as_the_look_showed_it']),
    'device_where_lines_guesses_among_several_rows': (
        'tap the first of several rows that satisfy where.lines',
        [('mobile.py', "    if len(matched) != 1 or len(shown_matches) != 1:", "    if not matched:"),
         ('mobile.py', "    only = matched[0]\n", "    only = matched[0]\n    shown_matches = matched\n")],
        ['test_mobile.RecordsOnDevices.test_several_or_no_matching_rows_tap_nothing_and_show_the_lines']),
    'device_agent_never_bootstrapped': (
        'leave the iOS agent install to the user: refuse mobile_device_agent_missing without installing',
        [('mobile.py', "        self.installer(device)\n        self.installed.append(device)\n", "        raise MobileGap('mobile_device_agent_missing', 'install it yourself')\n")],
        ['test_mobile.LookOnDevices.test_a_missing_ios_agent_is_installed_once_and_the_read_retried_once']),
    'device_agent_install_repeated': (
        'run the install again when the agent is still missing after it (a loop on a device that cannot have it)',
        [('mobile.py', "            if gap.reason == 'mobile_device_agent_missing':\n                raise MobileGap('mobile_device_agent_missing', 'the iOS agent was installed but", "            if gap.reason == 'mobile_device_agent_missing':\n                self.installer(device)\n                raise MobileGap('mobile_device_agent_missing', 'the iOS agent was installed but")],
        ['test_mobile.LookOnDevices.test_an_agent_still_missing_after_the_install_is_refused_after_exactly_one_retry']),
    # CE-FACADE-011 (#41): response budgets and trims.
    'response_notice_on_every_response': (
        'send the untrusted-text sentence on every response again (the flag is the per-response marker; the sentence is news only once per window)',
        [('core.py', "        if not self._notice_sent or new:", "        if True:")],
        ['test_response_budget.NoticeOnlyWhereItIsNews.test_the_first_response_has_the_sentence_and_the_second_look_of_the_same_window_omits_it_but_keeps_the_flag']),
    'response_notice_never_for_a_new_window': (
        'send the sentence only in the first response of the server: a second window arrives without it',
        [('core.py', "        if not self._notice_sent or new:", "        if not self._notice_sent:")],
        ['test_response_budget.NoticeOnlyWhereItIsNews.test_a_do_on_a_window_already_seen_omits_it_and_a_response_from_a_new_window_has_it_again',
         'test_response_budget.NoticeOnlyWhereItIsNews.test_pages_opened_by_read_pages_and_a_navigated_title_count_as_new']),
    'response_summary_repeats_what_the_look_showed': (
        'put the whole page text and every control into the do summary again',
        [('plan.py', "    if before:  # CE-FACADE-011", "    if False:  # CE-FACADE-011")],
        ['test_response_budget.DoCarriesWhatChanged.test_the_summary_after_a_look_carries_only_the_new_text_and_counts_what_it_left_out']),
    'response_summary_remembers_what_left': (
        'keep every line ever shown as known (a toast that leaves and comes back is invisible)',
        [('plan.py', "{t for t in texts if t in known['text']} | set(shown['text'])", "set(known['text']) | set(shown['text'])")],
        ['test_response_budget.DoCarriesWhatChanged.test_without_a_look_the_summary_is_complete_and_a_toast_that_leaves_and_returns_is_news_again']),
    'response_settle_after_a_proven_wait': (
        'settle (SETTLE_DELAY_S and another walk) after an idle wait that already showed the same tree',
        [('core.py', "if pending_count is None or pending_count != len(result.get('elements') or []):", "if True:")],
        ['test_response_budget.SettleLatency.test_a_look_that_waited_for_pressable_buttons_and_saw_the_same_tree_does_not_also_settle']),
    'response_settle_skipped_though_the_tree_moved': (
        'skip the settle after every actions_pending wait, even when the element count moved',
        [('core.py', "if pending_count is None or pending_count != len(result.get('elements') or []):", "if pending_count is None:")],
        ['test_response_budget.SettleLatency.test_a_tree_that_moved_during_the_wait_still_settles']),
    'response_long_hint': (
        'a hint over 240 characters restating the manual',
        [('plan.py', "    'budget_exceeded': 'The plan ran out of time before step %(n)d finished.", "    'budget_exceeded': 'The plan ran out of time and the whole manual follows, repeated at length so that no agent can miss any of it: look first, then do, expect is the proof, every step needs an expect, nothing is clicked blind, stop and ask the user on refusals, and so on. Step %(n)d finished.")],
        ['test_response_budget.HintsAddTheNextCall.test_no_hint_in_the_sources_is_over_240_characters',
         'test_response_budget.HintsAddTheNextCall.test_every_plan_hint_with_its_steps_done_suffix_is_within_the_cap']),
    'response_every_schema_title_stripped': (
        'strip the generated titles by also deleting the property named title',
        [('server.py', "                for child in value.values():slim_schema(child)", "                for child in value.values():slim_schema(child)\n                value.pop('title', None)")],
        ['test_response_budget.ToolListIsBounded.test_the_generated_schema_titles_are_gone_but_a_property_named_title_stays']),
    'response_do_description_repeats_the_schema': (
        'copy a plan step field description into the do docstring as well',
        [('server.py', "    \"\"\"Default path. Call `look` first", "    \"\"\"Default path. press only: which record (lines or fields). Without where, control names the one unique control to press. Call `look` first")],
        ['test_response_budget.ToolListIsBounded.test_each_parameter_is_documented_once_and_the_docstring_does_not_repeat_the_schema']),
    'upload_with_a_stale_ref': (
        'upload step (#5): another snapshot of the tab between the fresh default one and the set (refs die with any newer snapshot)',
        [('browser.py', "    chosen = pick_input(file_inputs(snapshot), control)\n", "    chosen = pick_input(file_inputs(snapshot), control)\n    page_of(f, target, tab)\n")],
        ['test_upload.Sends.test_the_only_file_input_is_used_and_the_expect_makes_it_done', 'test_upload.Sends.test_the_ref_comes_from_a_fresh_default_snapshot_taken_right_before_the_set']),
    'upload_picks_the_first_of_several_inputs': (
        'upload step (#5): with several file inputs and no control, take the first',
        [('browser.py', "    if control is None and len(inputs) == 1:\n        return inputs[0]", "    if control is None:\n        return inputs[0]")],
        ['test_upload.Choosing.test_several_inputs_without_control_is_refused_listing_ids_not_picking_the_first']),
    'upload_follows_a_symlink': (
        'upload step (#5): stat the path instead of lstat, so a symlink to a real file passes',
        [('browser.py', "            mode = os.lstat(path).st_mode", "            mode = os.stat(path).st_mode")],
        ['test_upload.FilesAreChecked.test_a_symlink_is_refused_even_to_a_real_file']),
    'upload_accepts_a_relative_path': (
        'upload step (#5): let a relative path through (the Driver would resolve it against its own directory)',
        [('browser.py', "        if not os.path.isabs(path):", "        if False:")],
        ['test_upload.FilesAreChecked.test_a_relative_path_is_refused']),
    'upload_done_without_the_expect': (
        'upload step (#5): done because the Driver said ok, the expect never read',
        [('plan.py', "                result = {'status': 'done' if kind == 'close_tab' else 'delivered_unverified', 'delivery': 'delivered'}\n                if step.get('expect'):",
          "                result = {'status': 'done' if kind in ('close_tab', 'upload') else 'delivered_unverified', 'delivery': 'delivered'}\n                if step.get('expect') and kind != 'upload':")],
        ['test_upload.Proof.test_done_needs_the_expect_to_be_seen_not_just_delivery']),
    'upload_echoes_the_path': (
        'upload step (#5): name the offending file by its full path in the refusal',
        [('browser.py', "        name = os.path.basename(path)[:80] or 'file %d' % index", "        name = path if isinstance(path, str) and path else 'file %d' % index")],
        ['test_upload.FilesAreChecked.test_a_symlink_is_refused_even_to_a_real_file', 'test_upload.FilesAreChecked.test_the_message_names_the_basename_only']),
    'device_swipe_done_when_the_list_did_not_change': (
        'swipe step: report it done because mobile-mcp answered "Swiped", without a changed element list',
        [('mobile.py', "        if signature(after) != signature(before):\n            return {'status': 'done', 'delivery': 'delivered', 'selected': selected, 'verification'", "        if True:\n            return {'status': 'done', 'delivery': 'delivered', 'selected': selected, 'verification'")],
        ['test_mobile.DoSwipe.test_a_swipe_that_changed_nothing_is_screen_unchanged_not_done']),
    'device_launch_takes_the_first_of_several_matching_apps': (
        'launch step: break a tie between several matching apps by launching the first',
        [('mobile.py', "        if len(found) == 1:\n            return found[0], None\n        if found:\n            return None, {'reason': 'app_ambiguous'", "        if found:\n            return found[0], None\n        if found:\n            return None, {'reason': 'app_ambiguous'")],
        ['test_mobile.DoLaunch.test_several_apps_with_the_name_are_refused_with_the_candidates_and_nothing_is_launched']),
    'device_launch_done_on_the_launch_answer': (
        'launch step: done because mobile-mcp said "Launched app", the fresh screen never checked against expect',
        [('mobile.py', "    return x.settle(step, before, LOAD_DELAYS, extra={'selected': selected})\n\n\ndef step_swipe", "    return {'status': 'done', 'delivery': 'delivered', 'selected': selected}\n\n\ndef step_swipe")],
        ['test_mobile.DoLaunch.test_launch_never_reports_done_on_expect_text_that_was_already_there',
         'test_mobile.DoLaunch.test_a_launch_that_changes_nothing_is_screen_unchanged_not_done']),
    'checkbox_done_without_the_state_flipping': (
        'a checkbox press is reported done because it was delivered (or its label is still on the page), not because its checked state flipped',
        [('forms.py', "        return {'final': marker == want, 'state': marker, 'gone': False}", "        return {'final': True, 'state': marker, 'gone': False}")],
        ['test_forms.Checkbox.test_the_label_still_on_the_page_is_not_proof_the_state_is']),
    'checkbox_pressed_when_already_in_the_wanted_state': (
        'press the checkbox whenever asked: a box already ticked is unticked by the "tick" step',
        [('forms.py', "    if want == before:\n        return _result('done', route='already_in_state'", "    if False:\n        return _result('done', route='already_in_state'")],
        ['test_forms.Checkbox.test_a_box_already_in_the_wanted_state_is_not_pressed_because_a_press_would_undo_it']),
    'select_done_when_the_displayed_value_differs': (
        'a select step is reported done when the Driver answered ok, whatever the select displays on a fresh read',
        [('forms.py', "        return {'final': shown == label, 'shown': shown, 'gone': False}", "        return {'final': True, 'shown': shown, 'gone': False}")],
        ['test_forms.Select.test_the_proof_is_a_fresh_read_not_the_drivers_answer', 'test_forms.Select.test_a_different_displayed_value_is_never_done']),
    'select_option_matched_loosely': (
        'accept the option the Driver picked case-insensitively: "billing" is not the exact visible label "Billing"',
        [('forms.py', "        return {'final': shown == label, 'shown': shown, 'gone': False}", "        return {'final': (shown or '').casefold() == label.casefold(), 'shown': shown, 'gone': False}")],
        ['test_forms.Select.test_a_different_displayed_value_is_never_done']),
    'select_opened_as_a_native_popup': (
        'press the select to open its popup instead of setting its value',
        [('forms.py', "        answer = f.driver.call('set_value', args)", "        answer = f.driver.call('click', {k: v for k, v in args.items() if k != 'value'})")],
        ['test_forms.Select.test_the_option_is_chosen_by_its_exact_label_without_opening_the_popup_and_proved_by_the_displayed_value']),
    'unresolved_ax_window_gives_up_at_once': (
        'a listed window without an AX window yet is refused on the first poll (what the look did before)',
        [('core.py', "                if n == len(AX_WINDOW_RETRY_DELAYS) or not str(error).startswith('driver_snapshot_unavailable'):", "                if True:")],
        ['test_look.AxWindowNotYetResolved.test_a_window_that_resolves_on_the_second_poll_is_looked_at_after_one_bounded_wait',
         'test_look.AxWindowNotYetResolved.test_a_window_that_resolves_on_the_third_poll_is_looked_at_too']),
    'unresolved_ax_window_waits_without_a_bound': (
        'raise the AX-window delays (and the clock guard never trips on a fake clock) so a window that never resolves is waited for a long time',
        [('core.py', "AX_WINDOW_RETRY_DELAYS = (0.5, 1.0, 1.5)", "AX_WINDOW_RETRY_DELAYS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)")],
        ['test_look.AxWindowNotYetResolved.test_a_window_that_never_resolves_ends_in_the_same_typed_refusal_after_a_few_bounded_seconds']),
    'unresolved_ax_window_ignores_the_look_bound': (
        'drop the LOOK_WAIT_MAX_S clock guard: every poll waits in the Driver and the retries run past the look bound',
        [('core.py', "                if self.clock() - began + delay + 2 * DRIVER_LAUNCH_WAIT_MS / 1000 > LOOK_WAIT_MAX_S:\n                    raise\n                self.sleep(delay)", "                self.sleep(delay)")],
        ['test_look.AxWindowNotYetResolved.test_the_wait_never_passes_the_look_bound_even_when_every_poll_waits_in_the_driver']),
    'actions_wait_for_the_ax_window': (
        'the AX-window wait also applies to the observation an action revalidates on',
        [('core.py', "self._observe_resolved(pid, window_id, timeout, began) if wait_ready else self._observe_once(pid, window_id, timeout)", "self._observe_resolved(pid, window_id, timeout, began)")],
        ['test_look.AxWindowNotYetResolved.test_an_action_observation_never_waits_for_the_ax_window']),
}


def stage(tmp):
    shutil.copytree(ROOT / 'computer_use', tmp / 'computer_use', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'scripts', tmp / 'scripts', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))  # a copy: a patch must never reach the real file through a symlink
    for name in ('inference', 'skills', 'docs'):
        (tmp / name).symlink_to(ROOT / name)


def run_tests(tmp, names):
    done = subprocess.run([sys.executable, '-m', 'unittest', *names], cwd=str(tmp / 'computer_use'), capture_output=True, text=True, timeout=600)
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
                path = tmp / 'computer_use' / filename;text = path.read_text()
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
