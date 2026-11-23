# Reward wrapper demo

This demo used a generated Python blueprint package and a temporary copy of its
target repository. It executed the emitted `tests/test.sh` and
`solution/solve.sh`; it is local wrapper evidence, not a Harbor trial.

Native command:

```text
python3 -m unittest discover -s tests -p test_task_factory.py -v
```

Observed results:

```text
Baseline:      test.sh exit 1; reward.txt = 0
Oracle script: solve.sh exit 0
After oracle:  test.sh exit 0; reward.txt = 1
```

The generated package manifest still remains `not_validated` until Harbor
`nop` and `oracle` trials produce the required rewards.
