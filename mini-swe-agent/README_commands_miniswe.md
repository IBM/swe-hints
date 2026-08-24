Minimax m2.5

### m25 + swe bench pro + defuse
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/defuse2_relaxed/swebench_pro_defuse2.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_sel_defuse_relaxed

### m25 + swe bench pro + no code
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/nocode/swebench_pro_nocode.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_sel_nocode

### m25 + swe bench pro + fea brief
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/fea_brief/swebench_pro_fea_brief.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_sel_fea_brief

### m25 + swe bench pro + swe pro
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/swe_pro/swebench_pro_official.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_sel_pro

### m25 + swe bench pro + no hint
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/nohint/swebench_pro_nohint.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_sel_nohint

### m25 + swe rebench + defuse
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_selection/mini_swe/defuse2_relaxed/swerebench_defuse2.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_sel_defuse_relaxed

### m25 + swe rebench + nocode
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_selection/mini_swe/nocode/swerebench_nocode.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_sel_nocode

### m25 + swe rebench + fea brief
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_selection/mini_swe/fea_brief/swerebench_fea_brief.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_sel_fea_brief

### m25 + swe rebench + swe pro
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_selection/mini_swe/swe_pro/swerebench_swe_pro.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_sel_pro

### m25 + swe rebench + no hint
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_selection/mini_swe/nohint/swerebench_nohint.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_sel_nohint

### m25 + doc2feat + defuse
mini-extra doc2feat \
  -c doc2feat.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/defuse2_relaxed/ncbench_defuse2.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_doc2feat_sel_defuse_relaxed

### m25 + doc2feat + nocode
mini-extra doc2feat \
  -c doc2feat.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/nocode/ncbench_nocode.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_doc2feat_sel_nocode

### m25 + doc2feat + fea brief
mini-extra doc2feat \
  -c doc2feat.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/fea_brief/ncbench_fea_brief.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_doc2feat_sel_fea_brief

### m25 + doc2feat + swe pro
mini-extra doc2feat \
  -c doc2feat.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/swe_pro/ncbench_swe_pro.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_doc2feat_sel_pro

### m25 + doc2feat + no hint
mini-extra doc2feat \
  -c doc2feat.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_selection/mini_swe/nohint/ncbench_nohint.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_doc2feat_nohint









 #===================== DEFUSE Selection, Different Projection ==========================#

### m25 + swe bench pro + no code
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_projection/mini_swe/nocode/swe_pro_nocode.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_proj_nocode

### m25 + swe bench pro + fea brief
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_projection/mini_swe/fea_brief/swe_pro_fea_brief.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_proj_fea_brief

### m25 + swe bench pro + swe pro
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/identity_projection/mini_swe/swe_pro/swe_pro_swe_pro.jsonl \
  --workers 8 \
  --output ./experiments/m25/bench_swe_pro_proj_pro



### m25 + swe bench pro + swe pro
mini-extra swebench \
  -c swebench_pro_hints.yaml \
  -c rits_swebench_minimax_m25.yaml \
  --subset /PATH/TO/hints_publish/results/miniswe_swe_pro/oracle_patch_interface_retrieved.jsonl \
  --workers 12 \
  --output ./loo/swe_pro_oracle_m25

results/miniswe_swe_pro/interface_retrieved_hints_nonempty_all_hints_v3.jsonl


### m25 + swe rebench + nocode
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_projection/mini_swe/nocode/swerebench_nocode.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_proj_nocode

### m25 + swe rebench + fea brief
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_projection/mini_swe/fea_brief/swerebench_fea_brief.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_proj_fea_brief

### m25 + swe rebench + swe pro
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_projection/mini_swe/swe_pro/swerebench_swe_pro.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_proj_pro

### m25 + swe rebench + nohint
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_minimax_m25.yaml \
    --subset /PATH/TO/hints_publish/identity_projection/mini_swe/nohint/swerebench_nohint.jsonl \
    --workers 8 \
    --output ./experiments/m25/bench_swe_rebench_proj_nohint


