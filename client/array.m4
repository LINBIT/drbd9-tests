m4_divert(`-1')
m4_define(`m4_set_array',
  `m4_define(m4_format(``$1[%s]'', `$2'), `$3')')
m4_define(`m4_get_array',
  `m4_defn(m4_format(``$1[%s]'', `$2'))')
m4_define(`m4_define_array',
  `m4_define(`$1',
    `m4_ifelse'(m4_dquote(m4_quote(`$'`#'), 1,
      `m4_get_array'(m4_dquote(`$1', m4_quote(`$'`1'))),
      `m4_set_array'(m4_dquote(`$1', m4_quote(`$'`1'), m4_quote(`$'`2'))))))')
m4_define(`m4_next_array',
  `m4_define(`$1',
    `m4_define'(m4_dquote(`_CURRENT_$1[$'`1]'),m4_quote(`m4_ifdef'(m4_dquote(`_CURRENT_$1[$'`1]'), m4_dquote(`m4_incr'(`m4_defn'(m4_dquote(`_CURRENT_$1[$'`1]')))), 1))) `m4_get_array'(m4_quote(`m4_format'(```$1%s''', `m4_defn'(m4_dquote(`_CURRENT_$1[$'`1]')))), m4_dquote(`$'`1')))')
m4_divert`'m4_dnl
