"""The upload plan step (#5 workaround): browser_set_input_files assigns the plan's local files to ONE exact live <input type=file>, no native picker.

The Driver's browser tools are test_browser.BrowserDriver plus the shapes measured live on the agent browser (2026-10-01): a default
get_browser_state snapshot answers refs [{frame:'main', node:'input', label:'id=f type=file', ref:'p139:1'}, ...] (other nodes carry null or other labels);
a ref dies with ANY newer snapshot of the same tab (semantic_v2 included); browser_set_input_files answers {status:'ok', file_count, frame, ref, tab_id,
target_id}. No desktop, browser or network. Each test names the tempting wrong patch it fails.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import browser
import test_browser as tb
from core import MUTATING_TOOLS
from plan import HINTS

EXPECT = 'Dr. Priya Shah'  # visible in the real captured Chrome tree the fake serves


def refs(*inputs, extra=True):
    out = [{'frame': 'main', 'node': 'a', 'label': None, 'ref': 'p139:0'}] if extra else []
    for i, label in enumerate(inputs, 1):
        out.append({'frame': 'main', 'node': 'input', 'label': label, 'ref': 'p139:%d' % i})
    if extra:
        out += [{'frame': 'main', 'node': 'input', 'label': 'id=q type=text', 'ref': 'p139:90'}, {'frame': 'main', 'node': 'button', 'label': 'type=file', 'ref': 'p139:91'}]
    return out


class UploadDriver(tb.BrowserDriver):
    def __init__(self):
        super().__init__()
        self.inputs = refs('id=f type=file');self.epoch = 0;self.minted_epoch = {};self.sets = [];self.set_mode = 'ok';self.calls_log = []
    def call(self, tool, args, timeout=20):
        if tool == 'get_browser_state' and 'target_id' in args:
            self.calls_log.append((tool, args.get('snapshot_format')))
            self.epoch += 1  # any snapshot invalidates every earlier ref of the tab
            if args.get('snapshot_format') is None:
                self.browser_calls.append((tool, dict(args)))
                for item in self.inputs:
                    self.minted_epoch[item['ref']] = self.epoch
                return {'status': 'ok', 'mode': 'snapshot', 'refs': [dict(i) for i in self.inputs], 'page': {'url': tb.BOOKING, 'title': 'Booking'}}
        if tool == 'browser_set_input_files':
            self.calls_log.append((tool, None))
            self.browser_calls.append((tool, dict(args)))
            self.sets.append(dict(args))
            if self.set_mode == 'refuse':
                return {'status': 'refused', 'refusal': {'code': 'browser_input_not_file'}}
            if self.set_mode == 'permission':
                return {'status': 'refused', 'refusal': {'code': 'browser_consent_required'}}
            if self.minted_epoch.get(args['ref']) != self.epoch:
                return {'status': 'refused', 'refusal': {'code': 'browser_ref_stale'}}
            count = len(args['files']) - (1 if self.set_mode == 'short' else 0)
            return {'status': 'ok', 'file_count': count, 'frame': 'main', 'ref': args['ref'], 'tab_id': args['tab_id'], 'target_id': args['target_id']}
        return super().call(tool, args, timeout)


class Base(tb.Base):
    def setUp(self):
        super().setUp()
        self.driver = UploadDriver();self.f.driver = self.driver
        self.dir = tempfile.mkdtemp();self.dir = os.path.realpath(self.dir)
        self.a, self.b = self.make('cv.pdf'), self.make('photo.png')
    def make(self, name):
        path = os.path.join(self.dir, name);Path(path).write_bytes(b'x');return path
    def upload(self, files=None, expect=EXPECT, **kw):
        step = {'do': 'upload', 'files': [self.a] if files is None else files, 'expect': expect, **kw}
        return self.plan([step])
    def no_path(self, r):
        self.assertNotIn(self.dir, json.dumps(r), 'a path must never come back')


class Sends(Base):
    def test_the_only_file_input_is_used_and_the_expect_makes_it_done(self):
        r = self.upload()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(len(self.driver.sets), 1)
        sent = self.driver.sets[0]
        self.assertEqual((sent['files'], sent['ref']), ([self.a], 'p139:1'))
        self.assertEqual(r['steps'][0]['do'], 'upload')
        self.no_path(r)

    def test_the_ref_comes_from_a_fresh_default_snapshot_taken_right_before_the_set(self):
        # Wrong patch: reuse a ref from an earlier snapshot (a look's semantic_v2, a previous step): the Driver refuses it as stale.
        r = self.plan([{'do': 'goto', 'url': tb.BOOKING, 'expect': EXPECT}, {'do': 'upload', 'files': [self.a], 'expect': EXPECT}])
        self.assertEqual(r['status'], 'done', r)
        log = self.driver.calls_log
        at = log.index(('browser_set_input_files', None))
        self.assertEqual(log[at - 1], ('get_browser_state', None), 'the default snapshot is the last browser call before the set')
        self.assertEqual(self.driver.sets[0]['ref'], 'p139:1')

    def test_several_files_are_sent_in_order(self):
        r = self.upload([self.a, self.b])
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.sets[0]['files'], [self.a, self.b])

    def test_a_file_input_among_other_inputs_and_non_input_nodes_is_found_by_node_and_label(self):
        self.driver.inputs = refs('id=up type=file', extra=True)
        r = self.upload()
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.sets[0]['ref'], 'p139:1', 'not the text input, not the button labelled type=file')

    def test_upload_is_a_mutating_step_the_facade_treats_as_mutating(self):
        self.assertIn('browser_set_input_files', MUTATING_TOOLS)


class Choosing(Base):
    def setUp(self):
        super().setUp()
        self.driver.inputs = refs('id=f type=file', 'id=g type=file', 'name=h type=file')

    def test_several_inputs_without_control_is_refused_listing_ids_not_picking_the_first(self):
        # Wrong patch: take the first file input when there are several.
        r = self.upload()
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('refused', 'upload_input_ambiguous'), r)
        self.assertEqual(self.driver.sets, [])
        self.assertIn('f', r['steps'][0]['message']);self.assertIn('g', r['steps'][0]['message'])
        self.assertEqual(r['hint'], HINTS['upload_input_ambiguous'] % {'n': 1})
        self.no_path(r)

    def test_control_picks_exactly_that_input_by_id(self):
        r = self.upload(control='g')
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.sets[0]['ref'], 'p139:2')

    def test_control_may_be_the_name_when_no_id_matches(self):
        r = self.upload(control='h')
        self.assertEqual(self.driver.sets[0]['ref'], 'p139:3')

    def test_a_control_that_matches_no_input_is_refused_not_guessed(self):
        # Wrong patch: substring match, or fall back to the first input.
        for control in ('x', 'f ', 'ff', ''):
            self.driver.sets.clear()
            r = self.upload(control=control)
            self.assertEqual(r['status'], 'refused', (control, r))
            self.assertEqual(self.driver.sets, [], control)
        r = self.upload(control='x')
        self.assertEqual(r['steps'][0]['reason'], 'upload_input_ambiguous')

    def test_control_must_match_even_when_there_is_one_input(self):
        self.driver.inputs = refs('id=f type=file')
        r = self.upload(control='other')
        self.assertEqual(r['steps'][0]['reason'], 'upload_input_ambiguous', r)
        self.assertEqual(self.driver.sets, [])

    def test_two_inputs_with_the_same_id_are_ambiguous(self):
        self.driver.inputs = refs('id=f type=file', 'id=f type=file')
        r = self.upload(control='f')
        self.assertEqual(r['steps'][0]['reason'], 'upload_input_ambiguous', r)

    def test_no_file_input_names_the_native_picker_and_does_not_click(self):
        self.driver.inputs = refs(extra=True)
        r = self.upload()
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('refused', 'upload_no_file_input'), r)
        self.assertEqual((self.driver.sets, self.driver.executed), ([], []))
        self.assertIn('#5', r['hint']);self.assertIn('picker', r['hint'])


class FilesAreChecked(Base):
    def refused(self, r, reason='upload_file_invalid'):
        self.assertEqual((r['status'], r['steps'] and r['steps'][0].get('reason') or r.get('reason')), ('refused', reason), r)
        self.assertEqual(self.driver.browser_calls, [], 'nothing reaches the Driver')
        self.no_path(r)

    def test_a_relative_path_is_refused(self):
        # Wrong patch: accept a relative path (it would resolve against the Driver's own directory).
        before = os.getcwd();os.chdir(self.dir);self.addCleanup(os.chdir, before)
        self.refused(self.upload(['cv.pdf']))

    def test_a_symlink_is_refused_even_to_a_real_file(self):
        # Wrong patch: follow symlinks (stat instead of lstat).
        link = os.path.join(self.dir, 'link.pdf');os.symlink(self.a, link)
        r = self.upload([link])
        self.refused(r)
        self.assertIn('link.pdf', json.dumps(r))

    def test_a_missing_file_a_directory_and_a_non_string_are_refused(self):
        for bad in (os.path.join(self.dir, 'nope.pdf'), self.dir, 7, '', None):
            r = self.upload([bad])
            self.assertEqual(r['status'], 'refused', bad)
            self.assertEqual(self.driver.browser_calls, [])

    def test_one_bad_file_among_good_ones_sends_nothing(self):
        self.refused(self.upload([self.a, os.path.join(self.dir, 'gone.pdf')]))

    def test_at_most_32_files_and_at_least_one(self):
        files = [self.make('f%d' % i) for i in range(33)]
        self.assertEqual(self.upload(files)['status'], 'refused')
        self.assertEqual(self.upload([])['status'], 'refused')
        self.assertEqual(self.driver.browser_calls, [])
        self.assertEqual(self.upload(files[:32])['status'], 'done')

    def test_files_is_required_and_a_list(self):
        self.assertEqual(self.plan([{'do': 'upload', 'expect': EXPECT}])['status'], 'refused')
        self.assertEqual(self.upload(self.a)['status'], 'refused')

    def test_the_message_names_the_basename_only(self):
        r = self.upload([os.path.join(self.dir, 'secret-name.pdf')])
        self.assertIn('secret-name.pdf', json.dumps(r));self.no_path(r)

    def test_a_check_at_the_function_too(self):
        # Wrong patch: validate only in the plan, so a direct caller of browser.upload sends anything.
        with self.assertRaises(Exception) as caught:
            browser.upload(self.f, 1, 2, ['relative.txt'])
        self.assertIn('upload_file_invalid', str(caught.exception))
        self.assertEqual(self.driver.browser_calls, [])


class Proof(Base):
    def test_done_needs_the_expect_to_be_seen_not_just_delivery(self):
        # Wrong patch: report done because the Driver said ok.
        r = self.upload(expect='A confirmation that is not on this page')
        self.assertNotEqual(r['status'], 'done', r)
        self.assertEqual(r['delivery'], 'delivered')
        self.assertEqual(len(self.driver.sets), 1, 'never retried')

    def test_without_an_expect_the_last_step_is_delivered_unverified_with_the_standard_hint(self):
        r = self.upload(expect=None)
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertEqual(r['hint'], HINTS['upload_unverified'])
        self.assertIn('Do not repeat', r['hint'])

    def test_expect_is_required_on_a_non_final_upload(self):
        r = self.plan([{'do': 'upload', 'files': [self.a]}, {'do': 'verify', 'expect': EXPECT}])
        self.assertEqual((r['status'], r['reason']), ('refused', 'expect_required'), r)
        self.assertEqual(self.driver.browser_calls, [])

    def test_the_step_takes_only_its_own_keys(self):
        for extra in ({'url': tb.BOOKING}, {'text': 'x'}, {'where': {'lines': [{'line': 'eq', 'value': 'x'}]}}):
            r = self.upload(**extra)
            self.assertEqual(r['status'], 'refused', extra)
        self.assertEqual(self.driver.browser_calls, [])


class Refusals(Base):
    def test_a_driver_refusal_is_upload_refused_with_no_driver_text_and_no_path(self):
        self.driver.set_mode = 'refuse'
        r = self.upload()
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('refused', 'upload_refused'), r)
        self.assertEqual(r['delivery'], 'none');self.no_path(r)

    def test_a_missing_permission_is_permission_required_not_another_browser(self):
        self.driver.set_mode = 'permission'
        r = self.upload()
        self.assertEqual(r['steps'][0]['reason'], 'permission_required', r)

    def test_a_count_the_driver_does_not_confirm_is_not_done_and_may_have_delivered(self):
        self.driver.set_mode = 'short'
        r = self.upload([self.a, self.b])
        self.assertEqual((r['status'], r['steps'][0]['reason']), ('failed', 'upload_unconfirmed'), r)
        self.assertNotEqual(r['delivery'], 'none')
        self.assertEqual(len(self.driver.sets), 1)

    def test_every_upload_reason_has_a_hint_of_at_most_240_characters_naming_the_next_call(self):
        reasons = ('upload_file_invalid', 'upload_input_ambiguous', 'upload_no_file_input', 'upload_refused', 'upload_failed', 'upload_unconfirmed', 'upload_unverified')
        for reason in reasons:
            self.assertIn(reason, HINTS)
            self.assertLessEqual(len(HINTS[reason]), 240, reason)
            self.assertRegex(HINTS[reason], r'\b(Call|call)\b', reason)

    def test_the_step_is_not_for_devices(self):
        import plan
        self.assertIn('upload', plan.DO_KINDS)
        import inspect, mobile
        self.assertIn("'upload'", inspect.getsource(mobile))


if __name__ == '__main__':
    unittest.main()
