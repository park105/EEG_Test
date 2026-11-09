import unittest
import numpy as np
from brainficial.report_pilot import features, holm


class ReportPilotTests(unittest.TestCase):
    def test_onset_only_and_previous_three_seconds(self):
        wave = np.sin(2*np.pi*10*np.arange(8064)/128)
        wave[384:896] *= 2
        wave[896:] *= 100
        data = np.broadcast_to(wave,(40,40,8064))
        labels = np.tile([1.,2.,3.,7.],(40,1))
        f = features(data,labels)
        np.testing.assert_allclose(f.O2_alpha,10*np.log10(4),atol=1e-5)
        self.assertTrue(f.liking.eq(7).all())
        self.assertEqual(len(f.filter(regex="_alpha$").columns),32)

    def test_holm_unsorted(self):
        np.testing.assert_allclose(holm([.2,.01,.03]),[.2,.03,.06])
