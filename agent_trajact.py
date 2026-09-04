from tests.evals.agent_trajectory import DeviantPolicy, ScriptedPolicy, run_policy, score_trajectory, load_eval_set
import json

case = load_eval_set()['cases'][0]
r1 = score_trajectory(run_policy(ScriptedPolicy(case['expected_tools'],case['required_args']),case['user_input']),case['expected_tools'],case['required_args'])

with open("policy_results.json","w") as f:
    json.dump(r1,f,indent =4)

r2 = score_trajectory(run_policy(DeviantPolicy(),case['user_input']),case['expected_tools'],case['required_args'])

with open("policy_results.json","a") as f:
    json.dump(r2,f,indent=4)
