m4_divert(`-1')
m4_define(`m4_set_array',
  `m4_define(m4_format(``$1[%s]'', `$2'), `$3')')
m4_define(`m4_get_array',
  `m4_defn(m4_format(``$1[%s]'', `$2'))')
m4_define(`m4_define_array',
  `m4_translit(`m4_define(`$1',
    `m4_ifelse(`§#', 1,
      `m4_get_array(`$1', `§1')',
      `m4_set_array(`$1', `§1', `§2')')')',
  `§', `$')')
m4_define(`m4_next_array',
  `m4_translit(`m4_define(`$1',
    `m4_define(`_CURRENT_$1[§1]', m4_ifdef(`_CURRENT_$1[§1]', `m4_incr(m4_defn(`_CURRENT_$1[§1]'))', 1))m4_get_array(m4_format(``$1%s'', m4_defn(`_CURRENT_$1[§1]')), `§1')')',
  `§', `$')')
m4_divert`'m4_dnl
