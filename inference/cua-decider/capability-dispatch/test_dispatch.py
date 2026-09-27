import copy
import unittest

from dispatch import Engine, compile_plan, execute_bound, reduce_match, typed
from providers import span_schema


def example():
    return {
        'snapshot_id': 'now', 'kind': 'match', 'operation': 'click', 'coverage_complete': True,
        'fields': {'owner': {'description': 'Account owner name', 'type': 'text'},
                   'count': {'description': 'Units remaining', 'type': 'number'}},
        'predicates': [{'field': 'owner', 'value': 'Morgan'}],
        'order_by': [{'field': 'count', 'direction': 'asc'}],
        'candidate_ids': ['first', 'second', 'third'], 'fallback_id': 'fallback',
        'actions': [
            {'id': 'first', 'operation': 'click', 'evidence_text': 'Morgan 12'},
            {'id': 'second', 'operation': 'click', 'evidence_text': 'Morgan 7'},
            {'id': 'third', 'operation': 'click', 'evidence_text': 'Taylor 2'},
            {'id': 'fallback', 'operation': 'click', 'evidence_text': 'Notify me'},
        ],
    }


def spans(request):
    # Fixed approved evidence replay, not a replacement extractor.
    values = [('Morgan', '12'), ('Morgan', '7'), ('Taylor', '2')]
    out = {}
    for action, (name, count) in zip(request['actions'], values):
        out[action['id']] = {}
        for field, value in [('owner', name), ('count', count)]:
            start = action['evidence_text'].index(value)
            out[action['id']][field] = [{'text': value, 'start': start, 'end': start+len(value), 'confidence': .99}]
    return out


class DispatchGates(unittest.TestCase):
    def test_description_wire_contract_matches_upstream_schema_builder(self):
        # Independent API anchor: installed GLiNER2 Schema.entities(...).build()
        # places descriptions in entity_descriptions, not in entities values.
        schema = span_schema({'brand': 'Manufacturer name only'})
        self.assertEqual(schema['entities'], {'brand': ''})
        self.assertEqual(schema['entity_descriptions'], {'brand': 'Manufacturer name only'})

    def test_ce_cap_002_complete_request_taxonomy(self):
        described = example()
        plain = copy.deepcopy(described)
        for field in plain['fields'].values():
            field.pop('description')
        requests = [
            ({'kind': 'exact'}, []), (plain, ['gliner']), (described, ['gliner2']),
            ({**described, 'shape': 'records'}, ['gliner2.5']),
            ({**described, 'shape': 'relations'}, ['gliner2.5']),
            ({**described, 'shape': 'long_spans'}, ['gliner2.5']),
            ({**described, 'language': 'es'}, ['gliner2.5']),
            ({'kind': 'classify', 'labels': {'urgent': 'Needs immediate attention'}, 'label_actions': {'urgent': 'a'}}, ['decide']),
            ({'kind': 'semantic'}, ['jev']),
        ]
        for request, models in requests:
            with self.subTest(request=request):
                self.assertEqual(compile_plan(request)['models'], models)

    def test_ce_cap_001_extract_then_compare(self):
        request = example()
        provider = lambda step, req: {'evidence': spans(req)}
        result = Engine({'gliner2': provider}).decide(request, 'now')
        self.assertEqual(result['plan']['steps'][0]['method'], 'extract')
        self.assertEqual(result['action_id'], 'second')
        self.assertTrue(result['action_authorized'])

    def test_hybrid_extraction_and_classification_join_by_record(self):
        request = example()
        request['fields']['category'] = {'labels': {'billing': 'Payment matters', 'technical': 'Technical fault'}, 'min_confidence': .9}
        request['predicates'].append({'field': 'category', 'value': 'billing'})
        classes = {'evidence': {aid: {'category': [{'kind': 'class', 'text': label, 'confidence': .98}]} for aid, label in [('first', 'billing'), ('second', 'technical'), ('third', 'billing')]}}
        result = Engine({'gliner2': lambda s, r: {'evidence': spans(r)}, 'decide': lambda s, r: classes}).decide(request, 'now')
        self.assertEqual(result['plan']['models'], ['gliner2', 'decide'])
        self.assertEqual(result['action_id'], 'first')

    def test_id_and_serialization_order_are_not_evidence(self):
        request = example()
        evidence = spans(request)
        request['actions'].reverse()
        request['candidate_ids'].reverse()
        request['actions'][2]['id'] = 'opaque-new-id'
        request['candidate_ids'][1] = 'opaque-new-id'
        evidence['opaque-new-id'] = evidence.pop('second')
        self.assertEqual(reduce_match(request, evidence)['action_id'], 'opaque-new-id')

    def test_changed_values_and_reverse_order(self):
        request = example()
        request['order_by'][0]['direction'] = 'desc'
        self.assertEqual(reduce_match(request, spans(request))['action_id'], 'first')
        request['predicates'][0]['value'] = 'Taylor'
        self.assertEqual(reduce_match(request, spans(request))['action_id'], 'third')

    def test_fields_must_match_on_same_record(self):
        request = example()
        request['predicates'].append({'field': 'count', 'value': 2})
        self.assertEqual(reduce_match(request, spans(request))['action_id'], 'fallback')

    def test_missing_evidence_is_not_no_match(self):
        request = example()
        evidence = spans(request)
        evidence['second'].pop('count')
        self.assertEqual(reduce_match(request, evidence)['status'], 'defer')
        request['coverage_complete'] = False
        self.assertEqual(reduce_match(request, spans(request))['reason'], 'scope_incomplete')

    def test_known_failure_excludes_otherwise_unknown_record(self):
        request = example()
        evidence = spans(request)
        evidence['third'].pop('count')
        self.assertEqual(reduce_match(request, evidence)['action_id'], 'second')

    def test_fabricated_offsets_do_not_ground_values(self):
        request = example()
        evidence = spans(request)
        evidence['second']['owner'][0]['text'] = 'Morgan X'
        self.assertEqual(reduce_match(request, evidence)['status'], 'defer')

    def test_tied_values_do_not_use_id_order(self):
        request = example()
        request['order_by'] = []
        self.assertEqual(reduce_match(request, spans(request))['reason'], 'tied_matches')

    def test_conflicting_spans_are_unknown(self):
        request = example()
        evidence = spans(request)
        request['actions'][1]['evidence_text'] = 'Morgan 7 or 9'
        evidence['second']['count'].append({'text': '9', 'start': 12, 'end': 13, 'confidence': .99})
        self.assertEqual(reduce_match(request, evidence)['status'], 'defer')

    def test_wrong_sibling_operation_excluded(self):
        request = example()
        request['actions'][1]['operation'] = 'type'
        self.assertEqual(reduce_match(request, spans(request))['action_id'], 'first')

    def test_exact_control_bypasses_models_and_binds_payload(self):
        request = {'snapshot_id': 'now', 'kind': 'exact', 'operation': 'type', 'target': {'name': 'Email', 'role': 'textbox'}, 'actions': [{'id': 'e', 'name': 'Email', 'role': 'textbox', 'operation': 'type', 'arguments': {'ref': 'current-4', 'text': 'user@example.test'}}]}
        selection = Engine({}).decide(request, 'now')
        calls = []
        execute_bound(request, selection, 'now', lambda op, args: calls.append((op, args)))
        self.assertEqual(calls[0][1]['ref'], 'current-4')
        self.assertEqual(calls[0][1]['text'], 'user@example.test')
        with self.assertRaises(ValueError):
            execute_bound(request, selection, 'new', lambda *a: self.fail('stale execution'))

    def test_classification_maps_labels_only(self):
        request = {'snapshot_id': 'now', 'kind': 'classify', 'operation': 'click', 'labels': {'billing': 'Payment issue'}, 'label_actions': {'billing': 'queue'}, 'min_confidence': .9, 'actions': [{'id': 'queue', 'operation': 'click'}]}
        result = Engine({'decide': lambda s, r: {'label': 'billing', 'confidence': .95}}).decide(request, 'now')
        self.assertEqual(result['action_id'], 'queue')
        result = Engine({'decide': lambda s, r: {'label': 'billing', 'confidence': .4}}).decide(request, 'now')
        self.assertFalse(result['action_authorized'])

    def test_semantic_choice_still_requires_current_allowed_operation(self):
        request = {'snapshot_id': 'now', 'kind': 'semantic', 'operation': 'click', 'actions': [{'id': 'a', 'operation': 'click'}]}
        good = Engine({'jev': lambda s, r: {'choice': 'a'}}).decide(request, 'now')
        bad = Engine({'jev': lambda s, r: {'choice': 'invented'}}).decide(request, 'now')
        self.assertTrue(good['action_authorized'])
        self.assertFalse(bad['action_authorized'])

    def test_provider_availability_does_not_change_capability(self):
        request = {**example(), 'shape': 'relations'}
        result = Engine({'gliner2': lambda *a: self.fail('wrong adapter')}).decide(request, 'now')
        self.assertEqual(result['reason'], 'provider_unavailable')
        self.assertEqual(result['plan']['models'], ['gliner2.5'])

    def test_invalid_time_and_wrong_duration_units_rejected(self):
        for value in ['14:00 PM', '2:60 PM', '25:00']:
            with self.assertRaises(ValueError):
                typed(value, {'type': 'time'})
        with self.assertRaises(ValueError):
            typed('2:30 PM', {'type': 'duration_minutes'})
        self.assertEqual(typed('0.5 hours', {'type': 'duration_minutes'}), 30)

    def test_disabled_action_or_provider_failure_never_executes(self):
        request = example()
        request['actions'][1]['enabled'] = False
        self.assertEqual(reduce_match(request, spans(request))['action_id'], 'first')
        def failed_provider(*args):
            raise RuntimeError('unavailable')
        result = Engine({'gliner2': failed_provider}).decide(request, 'now')
        self.assertFalse(result['action_authorized'])
        self.assertEqual(result['reason'], 'provider_failed')

    def test_visual_only_not_sent_to_text_model(self):
        request = {'snapshot_id': 'now', 'kind': 'semantic', 'visual_only': True, 'operation': 'click', 'actions': []}
        result = Engine({'jev': lambda *a: self.fail('text path cannot see image')}).decide(request, 'now')
        self.assertFalse(result['action_authorized'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
