# Standalone general-access XOR visual cryptography construction

- Participants: {1,2,3,4,5}
- Minimal qualified family: {{1,2}, {1,3}, {1,4,5}, {2,3,4}, {2,3,5}}
- Maximal forbidden family: {{1,4}, {1,5}, {2,3}, {2,4,5}, {3,4,5}}
- Candidate pairs examined: 61
- Raw / deduplicated / nondominated: 51 / 18 / 5
- Exact solver: built-in exact binary branch-and-bound
- Optimal pixel expansion: **m* = 2**

## Share-allocation table

| Candidate | Selected | L | P_1 | P_2 | P_3 | P_4 | P_5 | Coverage | Covered qualified sets |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | yes | 01123 | T_0 | T_1 | T_1 | T_2 | T_3 | (1,1,1,0,0)^T | {1,2}, {1,3}, {1,4,5} |
| B | yes | 01233 | T_0 | T_1 | T_2 | T_3 | T_3 | (1,0,0,1,1)^T | {1,2}, {2,3,4}, {2,3,5} |
| C | no | 01233 | T_0 | T_1 | T_2 | T_3 | T_3 | (0,1,0,1,1)^T | {1,3}, {2,3,4}, {2,3,5} |
| D | no | 01234 | T_0 | T_1 | T_2 | T_3 | T_4 | (0,0,1,1,0)^T | {1,4,5}, {2,3,4} |
| E | no | 01234 | T_0 | T_1 | T_2 | T_3 | T_4 | (0,0,1,0,1)^T | {1,4,5}, {2,3,5} |

## Share-recovery relation table

| Candidate | Selected | Share-type formulas | Recovery relations | Security verified |
| --- | --- | --- | --- | --- |
| A | yes | T_0 = S XOR R_1 XOR R_2; T_1 = R_1 XOR R_2; T_2 = R_1; T_3 = R_2 | T_0 XOR T_1 = S; T_0 XOR T_2 XOR T_3 = S | yes |
| B | yes | T_0 = R_1 XOR R_2; T_1 = S XOR R_1 XOR R_2; T_2 = R_1; T_3 = R_2 | T_0 XOR T_1 = S; T_1 XOR T_2 XOR T_3 = S | yes |
| C | no | T_0 = S XOR R_1; T_1 = S XOR R_1 XOR R_2; T_2 = R_1; T_3 = R_2 | T_0 XOR T_2 = S; T_1 XOR T_2 XOR T_3 = S | yes |
| D | no | T_0 = S XOR R_2 XOR R_3; T_1 = S XOR R_1 XOR R_2; T_2 = R_1; T_3 = R_2; T_4 = R_3 | T_1 XOR T_2 XOR T_3 = S; T_0 XOR T_3 XOR T_4 = S | yes |
| E | no | T_0 = S XOR R_2 XOR R_3; T_1 = S XOR R_1 XOR R_3; T_2 = R_1; T_3 = R_2; T_4 = R_3 | T_1 XOR T_2 XOR T_4 = S; T_0 XOR T_3 XOR T_4 = S | yes |

## Exact 0-1 set-cover model

```text
min x_A + x_B + x_C + x_D + x_E
subject to
  x_A + x_B >= 1    ({1,2})
  x_A + x_C >= 1    ({1,3})
  x_A + x_D + x_E >= 1    ({1,4,5})
  x_B + x_C + x_D >= 1    ({2,3,4})
  x_B + x_C + x_E >= 1    ({2,3,5})
  x_A in {0,1}, x_B in {0,1}, x_C in {0,1}, x_D in {0,1}, x_E in {0,1}
optimum m* = 2; selected = {A,B}
```

## Image verification

Source: `phone.png`

- `recovered_1_2.png`: pixel-identical recovery
- `recovered_1_3.png`: pixel-identical recovery
- `recovered_1_4_5.png`: pixel-identical recovery
- `recovered_2_3_4.png`: pixel-identical recovery
- `recovered_2_3_5.png`: pixel-identical recovery
