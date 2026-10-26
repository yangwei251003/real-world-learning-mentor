"""Create only a fresh local learner state; optional test-only role templates."""
from pathlib import Path
import argparse,subprocess,sys,shutil
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--test-config',action='store_true');args=p.parse_args()
state=ROOT/'Learner_State'
if not state.exists():
 subprocess.run([sys.executable,str(ROOT/'.agents/skills/real-world-learning-mentor/scripts/state_tool.py'),'--state-dir',str(state),'init'],check=True)
else:
 subprocess.run([sys.executable,str(ROOT/'.agents/skills/real-world-learning-mentor/scripts/state_tool.py'),'--state-dir',str(state),'validate'],check=True)
if args.test_config:
 target=ROOT/'.codex'
 if target.exists():raise SystemExit('Existing .codex directory: review manually; no overwrite.')
 shutil.copytree(ROOT/'examples/codex',target)
 print('Copied historical role examples for deterministic tests only; model availability not verified.')
