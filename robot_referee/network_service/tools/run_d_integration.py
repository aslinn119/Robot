"""Run only the real D-strategy/C-referee integration checks; no robot actions."""
import io
import sys
import unittest
from datetime import datetime
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
sys.path.insert(0,str(root/'src'))
from test_d_integration import DIntegrationTests
output=io.StringIO()
result=unittest.TextTestRunner(stream=output,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DIntegrationTests))
report='D strategy + C referee integration (software only; no physical actions)\n58 legal strategy-tree paths (fixed game ID); at most 7 questions; actual D source snapshot.\n'+output.getvalue()
path=root/'runtime'/('d_integration_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.txt')
path.parent.mkdir(exist_ok=True)
path.write_text(report,encoding='utf-8')
print(report)
print(path)
sys.exit(0 if result.wasSuccessful() else 1)
