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
         ('plan.py', "        if not any(key[2] == look_id for key in f.looks):", "        if False:"),
         ('plan.py', "    if look_id is not None and not any(key[2] == look_id for key in f.looks):", "    if False:"),
         ('core.py', "                if lines_where['look'] is None:\n                    raise Gap(", "                if False:\n                    raise Gap("),
         ('plan.py', "    look = spec['look']\n    opts = look.get('opts', lk.DEFAULT_OPTS)", "    look = spec['look'] or {'terms': [], 'n': 10 ** 6}\n    opts = look.get('opts', lk.DEFAULT_OPTS)"),
         ('plan.py', "    if not same:\n        return {'defer': {'reason': 'page_changed_since_look'", "    if spec['look'] and not same:\n        return {'defer': {'reason': 'page_changed_since_look'")],
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
        [('look.py', "'untrusted_page_text': True, 'notice': NOTICE, ", ""), ('core.py', "            result.setdefault('untrusted_page_text', True);result.setdefault('notice', lookmod.NOTICE)", "            pass")],
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
        'cua_do responses carry page text without the untrusted marker (second review P2-C)',
        [('core.py', "            result.setdefault('untrusted_page_text', True);result.setdefault('notice', lookmod.NOTICE)", '            pass')],
        ['test_plan_review2.UntrustedEverywhere.test_plan_responses_carry_the_marker_in_every_page_text_field', 'test_plan_review2.UntrustedEverywhere.test_single_step_responses_carry_the_marker_and_no_page_text_in_hints']),
    'page_text_in_a_hint': (
        'a control label is put into a hint (second review P2-C)',
        [('core.py', "'control_needed': 'Each record has several controls (found.repeated_controls lists their labels). Call cua_do again with control=<the exact label of the one to press>.',", "'control_needed': 'Each record has several controls (%s). Call cua_do again with control=<the exact label of the one to press>.' % ', '.join(c['label'] for c in found['repeated_controls']),")],
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
        [('look.py', '    return sorted([path(i)] + [str(nodes[i].get(k)) for k in CONTROL_STATE_KEYS] for i in picked)', '    return sorted([str(i)] + [str(nodes[i].get(k)) for k in CONTROL_STATE_KEYS] for i in picked)')],
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
        [('core.py', "message='driver_call_failed: a Driver call failed; delivery and retryable say whether anything may have been clicked', attempts=", 'message=str(gap), attempts=')],
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
    'budget_look_reader': (
        'the default look reads through NuExtract (measured through the real server tools)',
        [('look.py', "        f.looks[(pid, window_id, response['look_id'])] = {", "        try:f.provider('reader').extract({'snapshot_id': state['raw']['snapshot_id'], 'task': 't', 'fields': {'x': 'x'}, 'records': [{'id': 'e1', 'text': 't'}]}, state['raw']['snapshot_id'])\n        except Exception:pass  # the fake reader counts the request before it looks for a pattern\n        f.looks[(pid, window_id, response['look_id'])] = {")],
        ['test_budget.DefaultPathBudget.test_look_then_plan_is_two_calls_with_no_reader_and_no_chooser_on_the_real_trees']),
}


def stage(tmp):
    shutil.copytree(ROOT / 'facade', tmp / 'facade', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'scripts', tmp / 'scripts', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))  # a copy: a patch must never reach the real file through a symlink
    for name in ('inference', 'skills', 'docs'):
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
