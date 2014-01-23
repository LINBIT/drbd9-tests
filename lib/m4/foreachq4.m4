m4_include(`forloop2.m4')m4_dnl
m4_divert(`-1')
# foreachq(x, `item_1, item_2, ..., item_n', stmt)
#   quoted list, version based on forloop
m4_define(`m4_foreachq',
`m4_ifelse(`$2', `', `', `_$0(`$1', `$3', $2)')')
m4_define(`_m4_foreachq',
`m4_pushdef(`$1', m4_forloop(`$1', `3', `$#',
  `$0_(`1', `2', m4_indir(`$1'))')`m4_popdef(
    `$1')')m4_indir(`$1', $@)')
m4_define(`_m4_foreachq_',
``m4_define(`$$1', `$$3')$$2`''')
m4_divert`'m4_dnl
