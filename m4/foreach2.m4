m4_include(`quote.m4')m4_dnl
m4_divert(`-1')
# m4_foreach(x, (item_1, item_2, ..., item_n), stmt)
#   parenthesized list, improved version
m4_define(`m4_foreach', `m4_pushdef(`$1')_$0(`$1',
  (m4_dquote(m4_dquote_elt$2)), `$3')m4_popdef(`$1')')
m4_define(`_m4_arg1', `$1')
m4_define(`_m4_foreach', `m4_ifelse(`$2', `(`')', `',
  `m4_define(`$1', _m4_arg1$2)$3`'$0(`$1', (m4_dquote(m4_shift$2)), `$3')')')
m4_divert`'m4_dnl
