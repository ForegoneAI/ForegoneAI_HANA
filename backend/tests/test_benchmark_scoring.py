import copy
import unittest
from backend.evaluation.scoring import equal, score_case, summarize, model_cost, evidence_correct, value_correct

G={'status':'present','value':100,'unit':'USD','abs_tolerance':.01}
E={'locations':[{'document_id':'d','page':4}]}
P={'status':'present','value':100,'unit':'USD','evidence':[{'document_id':'d','page':4}]}

class EvaluationTests(unittest.TestCase):
    def test_correct(self):
        rows,_=score_case({'fields':{'f':P}},{'f':G},{'f':E})
        self.assertEqual(summarize(rows)['grounded_accuracy'],1)
    def test_wrong_page_keeps_value_accuracy(self):
        p=copy.deepcopy(P);p['evidence'][0]['page']=3
        rows,_=score_case({'fields':{'f':p}},{'f':G},{'f':E})
        m=summarize(rows);self.assertEqual(m['field_accuracy'],1);self.assertEqual(m['evidence_page_accuracy'],0)
    def test_wrong_document(self):
        p=copy.deepcopy(P);p['evidence'][0]['document_id']='other'
        self.assertFalse(evidence_correct(p,G,E))
    def test_extra_bad_citation(self):
        p=copy.deepcopy(P);p['evidence'].append({'document_id':'d','page':99})
        self.assertFalse(evidence_correct(p,G,E))
    def test_omitted_is_not_missing_detection(self):
        g=dict(G,status='missing',value=None)
        rows,_=score_case({'fields':{}},{'f':g},{'f':{'locations':[]}})
        self.assertEqual(summarize(rows)['missing_detection_recall'],0)
    def test_explicit_missing(self):
        g=dict(G,status='missing',value=None);p=dict(P,status='missing',value=None,evidence=[])
        rows,_=score_case({'fields':{'f':p}},{'f':g},{'f':{'locations':[]}})
        self.assertEqual(summarize(rows)['missing_detection_f1'],1)
    def test_hallucinated_missing_value(self):
        g=dict(G,status='missing',value=None)
        rows,_=score_case({'fields':{'f':P}},{'f':g},{'f':{'locations':[]}})
        self.assertEqual(summarize(rows)['unsupported_extraction_rate_reference'],1)
    def test_wrong_scale_unit_and_sign(self):
        for v in (100000000,-100):self.assertFalse(value_correct(dict(P,value=v),G))
        self.assertFalse(value_correct(dict(P,unit='EUR'),G))
    def test_range_order(self):
        self.assertFalse(equal([18,20],[20,18]))
    def test_tolerance(self):
        self.assertTrue(equal(100,100.009,.01));self.assertFalse(equal(100,100.02,.01))
    def test_nonfinite_and_boolean(self):
        self.assertFalse(equal(float('nan'),100));self.assertFalse(equal(True,1))
    def test_conflict_candidates(self):
        g=dict(G,status='conflict',value=None,candidates=[100,200])
        p=dict(P,status='conflict',value=None,candidates=[200,100])
        self.assertTrue(value_correct(p,g))
        self.assertFalse(value_correct(dict(p,candidates=[100]),g))
        self.assertFalse(value_correct(dict(p,candidates=[100,100]),g))
    def test_conflict_needs_all_locations(self):
        g=dict(G,status='conflict',value=None,candidates=[100,200])
        e={'locations':[{'document_id':'d','page':4},{'document_id':'d','page':5}]}
        self.assertFalse(evidence_correct(P,g,e))
    def test_sheet_not_pdf_page(self):
        e={'locations':[{'document_id':'d','sheet':'Base','cell':'I12'}]}
        p=dict(P,evidence=[{'document_id':'d','sheet':'Base','cell':'i12'}])
        self.assertTrue(evidence_correct(p,G,e));self.assertFalse(evidence_correct(P,G,e))
    def test_unknown_cost(self):
        self.assertIsNone(model_cost({'fields':{}},{}))
    def test_cached_cost_multiple_calls(self):
        pricing={'test':{'input_per_million':2,'cached_input_per_million':1,'output_per_million':4}}
        p={'usage':[{'model':'test','input_tokens':1000,'cached_input_tokens':200,'output_tokens':100}]*2}
        self.assertAlmostEqual(model_cost(p,pricing),.0044)
    def test_bad_usage(self):
        rates={'test':{'input_per_million':1,'cached_input_per_million':1,'output_per_million':1}}
        self.assertIsNone(model_cost({'usage':[{'model':'test','input_tokens':1,'cached_input_tokens':2,'output_tokens':1}]},rates))
    def test_unexpected_fields(self):
        _,extras=score_case({'fields':{'f':P,'extra':P}},{'f':G},{'f':E})
        self.assertEqual(extras,['extra'])

if __name__=='__main__':unittest.main()
