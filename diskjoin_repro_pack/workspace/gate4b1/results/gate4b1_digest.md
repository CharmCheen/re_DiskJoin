# GATE4B1 ANALYSIS DIGEST

runs analyzed: 65 (matrix + seeds + holdout + verification)

## Consistency problems: 0
- NONE: trace/stats/IO-recompute/invariants/FP=0/dup=0/model xcheck all PASS

## Matrix: cache misses (miss | admit/evict/reject | eff_B req_B)

### p1 eb01
order | belady_reject | belady_forced | lru_forced
gorder | 172 (62/92/18) [351744B/1040384B] | 174 (62/112/0) [355456B/1052672B] | 301 (62/239/0) [634240B/1847296B]
identity | 195 (62/111/22) [397568B/1191936B] | 196 (62/134/0) [398976B/1200128B] | 362 (62/300/0) [748928B/2207744B]
random | 246 (62/111/73) [495424B/1486848B] | 249 (62/187/0) [508288B/1523712B] | 508 (62/446/0) [1071296B/3129344B]

### p1 eb10
order | belady_reject | belady_forced | lru_forced
gorder | 172 (62/91/19) [351104B/1028096B] | 173 (62/111/0) [353664B/1036288B] | 281 (62/219/0) [605824B/1732608B]
identity | 186 (62/98/26) [376576B/1138688B] | 187 (62/125/0) [375488B/1134592B] | 351 (62/289/0) [727360B/2154496B]
random | 237 (62/109/66) [480320B/1429504B] | 240 (62/178/0) [493504B/1454080B] | 491 (62/429/0) [1024000B/2998272B]

### p3 eb01
order | belady_reject | belady_forced | lru_forced
gorder | 164 (62/67/35) [330368B/974848B] | 165 (62/103/0) [329280B/974848B] | 273 (62/211/0) [571008B/1613824B]
identity | 134 (62/54/18) [274688B/806912B] | 134 (62/72/0) [273472B/806912B] | 222 (62/160/0) [457792B/1318912B]
random | 204 (62/83/59) [406848B/1216512B] | 208 (62/146/0) [412096B/1236992B] | 395 (62/333/0) [813184B/2338816B]

### p3 eb10
order | belady_reject | belady_forced | lru_forced
gorder | 161 (62/70/29) [325888B/958464B] | 161 (62/99/0) [324992B/954368B] | 250 (62/188/0) [528896B/1495040B]
identity | 133 (62/54/17) [272064B/798720B] | 133 (62/71/0) [272064B/798720B] | 219 (62/157/0) [452736B/1302528B]
random | 195 (62/81/52) [389120B/1167360B] | 197 (62/135/0) [394048B/1179648B] | 377 (62/315/0) [781440B/2232320B]

## GT evaluation (full oracle)
- p1 eb01: pairs=190149 GT=297600 TP=190149 FP=0 FN=107451 precision=1.0 recall=0.638942
- p1 eb10: pairs=187769 GT=297600 TP=187769 FP=0 FN=109831 precision=1.0 recall=0.630944
- p3 eb01: pairs=59151 GT=68029 TP=59151 FP=0 FN=8878 precision=1.0 recall=0.869497
- p3 eb10: pairs=58366 GT=68029 TP=58366 FP=0 FN=9663 precision=1.0 recall=0.857958
- w1h eb01: pairs=198710 GT=294556 TP=198710 FP=0 FN=95846 precision=1.0 recall=0.674609
- w1h eb10: pairs=196101 GT=294556 TP=196101 FP=0 FN=98455 precision=1.0 recall=0.665751
- w2h eb01: pairs=65746 GT=72502 TP=65746 FP=0 FN=6756 precision=1.0 recall=0.906816
- w2h eb10: pairs=65181 GT=72502 TP=65181 FP=0 FN=7321 precision=1.0 recall=0.899023

## Locality (per order; LRU stack distance < 62 = LRU-hittable)
ds eb order | acc | sd_med | sd_mean | sd<62 | frac | interslot | ws1 ws2 ws4 ws8 | top10
p1 01 gorder | 1484 | 22 | 31.26 | 1183 | 0.7972 | 5.218 | 12.4 19.5 29.3 43.9 | 0.2588
p1 01 identity | 1484 | 33 | 37.77 | 1122 | 0.7561 | 3.193 | 12.4 21.5 34.5 48.8 | 0.2588
p1 01 random | 1484 | 40 | 45.93 | 976 | 0.6577 | 1.933 | 12.4 22.9 39.2 60.3 | 0.2588
p1 10 gorder | 1435 | 21 | 30.23 | 1154 | 0.8042 | 5.101 | 12.0 18.8 28.3 42.0 | 0.2599
p1 10 identity | 1435 | 33 | 37.48 | 1084 | 0.7554 | 2.958 | 12.0 21.0 33.8 48.2 | 0.2599
p1 10 random | 1435 | 39 | 45.47 | 944 | 0.6578 | 1.765 | 12.0 22.3 38.2 59.0 | 0.2599
p3 01 gorder | 1685 | 20 | 27.3 | 1412 | 0.838 | 7.588 | 14.0 20.5 29.4 42.7 | 0.3893
p3 01 identity | 1685 | 21 | 26.39 | 1463 | 0.8682 | 6.521 | 14.0 21.6 30.8 42.3 | 0.3893
p3 01 random | 1685 | 30 | 37.05 | 1290 | 0.7656 | 4.084 | 14.0 24.2 38.5 56.9 | 0.3893
p3 10 gorder | 1594 | 19 | 26.47 | 1344 | 0.8432 | 6.908 | 13.3 19.7 28.4 41.8 | 0.3965
p3 10 identity | 1594 | 20 | 25.96 | 1375 | 0.8626 | 5.95 | 13.3 20.6 29.8 41.2 | 0.3965
p3 10 random | 1594 | 29 | 36.52 | 1217 | 0.7635 | 3.765 | 13.3 23.0 36.9 55.0 | 0.3965

## Capacity curves (miss @ cap; C=reject A=forced D=lru)
- p1 eb01 gorder: 
- p1 eb01 identity: 
- p3 eb01 gorder: 
- p3 eb01 identity: 
(full curves in results/gate4b1_capcurve.tsv; key caps 40/62/80 below)
ds eb order policy | miss@40 | miss@62 | miss@80
p1 01 gorder belady_forced | 270 | 174 | 140
p1 01 gorder belady_reject | 268 | 172 | 139
p1 01 gorder lru_forced | 465 | 301 | 206
p1 01 identity belady_forced | 336 | 196 | 141
p1 01 identity belady_reject | 332 | 195 | 141
p1 01 identity lru_forced | 646 | 362 | 227
p1 01 random belady_forced | 406 | 249 | 178
p1 01 random belady_reject | 401 | 246 | 178
p1 01 random lru_forced | 806 | 508 | 323
p1 10 gorder belady_forced | 253 | 173 | 138
p1 10 gorder belady_reject | 252 | 172 | 137
p1 10 gorder lru_forced | 442 | 281 | 216
p1 10 identity belady_forced | 319 | 187 | 138
p1 10 identity belady_reject | 317 | 186 | 137
p1 10 identity lru_forced | 621 | 351 | 221
p1 10 random belady_forced | 391 | 240 | 171
p1 10 random belady_reject | 384 | 237 | 170
p1 10 random lru_forced | 776 | 491 | 311
p3 01 gorder belady_forced | 244 | 165 | 132
p3 01 gorder belady_reject | 243 | 164 | 132
p3 01 gorder lru_forced | 415 | 273 | 192
p3 01 identity belady_forced | 219 | 134 | 120
p3 01 identity belady_reject | 216 | 134 | 120
p3 01 identity lru_forced | 396 | 222 | 155
p3 01 random belady_forced | 347 | 208 | 147
p3 01 random belady_reject | 344 | 204 | 147
p3 01 random lru_forced | 695 | 395 | 240
p3 10 gorder belady_forced | 233 | 161 | 130
p3 10 gorder belady_reject | 230 | 161 | 130
p3 10 gorder lru_forced | 390 | 250 | 185
p3 10 identity belady_forced | 209 | 133 | 120
p3 10 identity belady_reject | 206 | 133 | 120
p3 10 identity lru_forced | 374 | 219 | 155
p3 10 random belady_forced | 328 | 197 | 146
p3 10 random belady_reject | 324 | 195 | 146
p3 10 random lru_forced | 650 | 377 | 233

## Pruning ablation (gorder, belady_reject)
- p1: tasks 1484->1435 (-3.3%), dist_comp 1833576->1773186 (-3.3%), miss 172->172, eff 351744->351104 B, recall 0.638942->0.630944 (-0.80 pp)
- p3: tasks 1685->1594 (-5.4%), dist_comp 3274616->3153834 (-3.7%), miss 164->161, eff 330368->325888 B, recall 0.869497->0.857958 (-1.15 pp)

## Extra seeds (random order sensitivity, eb01)
- p1 belady_reject: seed20260101=246, seed20261102=239, seed424242=242
- p1 belady_forced: seed20260101=249, seed20261102=240, seed424242=243
- p1 lru_forced: seed20260101=508, seed20261102=488, seed424242=494
- p3 belady_reject: seed20260101=204, seed20261102=205, seed424242=199
- p3 belady_forced: seed20260101=208, seed20261102=206, seed424242=202
- p3 lru_forced: seed20260101=395, seed20261102=393, seed424242=379

## Holdout
- w1h_gorder_belady_reject_eb01: miss=173 tasks=1519 npairs=198710 recall=0.674609 fp=0
- w1h_gorder_belady_reject_eb10: miss=168 tasks=1466 npairs=196101 recall=0.665751 fp=0
- w1h_gorder_lru_forced_eb01: miss=288 tasks=1519 npairs=198710 recall=0.674609 fp=0
- w1h_identity_belady_reject_eb01: miss=176 tasks=1519 npairs=198710 recall=0.674609 fp=0
- w2h_gorder_belady_reject_eb01: miss=171 tasks=1766 npairs=65746 recall=0.906816 fp=0
- w2h_gorder_belady_reject_eb10: miss=156 tasks=1678 npairs=65181 recall=0.899023 fp=0
- w2h_gorder_lru_forced_eb01: miss=282 tasks=1766 npairs=65746 recall=0.906816 fp=0
- w2h_identity_belady_reject_eb01: miss=149 tasks=1766 npairs=65746 recall=0.906816 fp=0

## Timing (SUB-SECOND: recorded, NOT performance claims)
- p1_gorder_belady_forced_eb01: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.058s search~0.036s
- p1_gorder_belady_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.058s search~0.048s
- p1_gorder_belady_reject_eb01: n=5 wall[min/mean/max]=0.080/0.092/0.100s build~0.056s search~0.038s
- p1_gorder_belady_reject_eb10: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.046s search~0.048s
- p1_gorder_lru_forced_eb01: n=5 wall[min/mean/max]=0.080/0.094/0.100s build~0.055s search~0.040s
- p1_gorder_lru_forced_eb10: n=1 wall[min/mean/max]=0.120/0.120/0.120s build~0.059s search~0.060s
- p1_identity_belady_forced_eb01: n=1 wall[min/mean/max]=0.100/0.100/0.100s build~0.056s search~0.046s
- p1_identity_belady_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.058s search~0.050s
- p1_identity_belady_reject_eb01: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.056s search~0.036s
- p1_identity_belady_reject_eb10: n=1 wall[min/mean/max]=0.100/0.100/0.100s build~0.059s search~0.044s
- p1_identity_lru_forced_eb01: n=1 wall[min/mean/max]=0.100/0.100/0.100s build~0.059s search~0.045s
- p1_identity_lru_forced_eb10: n=1 wall[min/mean/max]=0.100/0.100/0.100s build~0.058s search~0.042s
- p1_random_belady_forced_eb01: n=1 wall[min/mean/max]=0.100/0.100/0.100s build~0.057s search~0.039s
- p1_random_belady_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.057s search~0.057s
- p1_random_belady_reject_eb01: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.047s search~0.042s
- p1_random_belady_reject_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.059s search~0.057s
- p1_random_lru_forced_eb01: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.057s search~0.052s
- p1_random_lru_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.054s search~0.054s
- p3_gorder_belady_forced_eb01: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.044s search~0.046s
- p3_gorder_belady_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.056s search~0.052s
- p3_gorder_belady_reject_eb01: n=5 wall[min/mean/max]=0.070/0.090/0.110s build~0.050s search~0.042s
- p3_gorder_belady_reject_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.055s search~0.052s
- p3_gorder_lru_forced_eb01: n=5 wall[min/mean/max]=0.110/0.122/0.140s build~0.053s search~0.070s
- p3_gorder_lru_forced_eb10: n=1 wall[min/mean/max]=0.130/0.130/0.130s build~0.059s search~0.069s
- p3_identity_belady_forced_eb01: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.055s search~0.041s
- p3_identity_belady_forced_eb10: n=1 wall[min/mean/max]=0.080/0.080/0.080s build~0.042s search~0.038s
- p3_identity_belady_reject_eb01: n=5 wall[min/mean/max]=0.080/0.092/0.100s build~0.053s search~0.043s
- p3_identity_belady_reject_eb10: n=1 wall[min/mean/max]=0.090/0.090/0.090s build~0.054s search~0.039s
- p3_identity_lru_forced_eb01: n=1 wall[min/mean/max]=0.100/0.100/0.100s build~0.055s search~0.041s
- p3_identity_lru_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.054s search~0.053s
- p3_random_belady_forced_eb01: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.054s search~0.059s
- p3_random_belady_forced_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.056s search~0.058s
- p3_random_belady_reject_eb01: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.056s search~0.056s
- p3_random_belady_reject_eb10: n=1 wall[min/mean/max]=0.110/0.110/0.110s build~0.055s search~0.059s
- p3_random_lru_forced_eb01: n=1 wall[min/mean/max]=0.130/0.130/0.130s build~0.055s search~0.081s
- p3_random_lru_forced_eb10: n=1 wall[min/mean/max]=0.120/0.120/0.120s build~0.054s search~0.068s