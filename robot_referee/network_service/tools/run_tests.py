"""Run shared C/D network integration tests without hardware calls."""
import io, sys, unittest
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
report='Shared network service: software tests; no hardware.\n'+stream.getvalue()
path=root/'runtime'/('network_checks_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.txt')
path.parent.mkdir(exist_ok=True)
path.write_text(report,encoding='utf-8')
print(report)
print(path)
sys.exit(0 if result.wasSuccessful() else 1)
