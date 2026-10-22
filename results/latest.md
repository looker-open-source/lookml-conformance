# LookML conformance scorecard, 2026-10-20

✅ pass · ❌ fail · ⚠️ adapter error · N/A not applicable (the tool does not produce that output). *confirmed* cases follow from the cited Looker documentation; *provisional* cases cover behavior the documentation leaves open and are pinned to a named public source.

## Summary (passed / applicable)

| Tool | Version | confirmed | provisional | All |
| --- | --- | --- | --- | --- |
| node-lookml-parser | `9.1.0` | 21 / 27 | 6 / 8 | **27 / 35** |
| OpenMetadata | `2.0.5.0` | 7 / 27 | 0 / 8 | **7 / 35** |
| DataHub | `1.7.0.14` | 14 / 27 | 1 / 8 | **15 / 35** |
| Dagster | `0.29.25` | 16 / 32 | 5 / 8 | **21 / 40** |

## Results

| Case | Status | node-lookml-parser | OpenMetadata | DataHub | Dagster |
| --- | --- | --- | --- | --- | --- |
| `r01_refinement_overrides_sql_table_name` | confirmed | ✅ | ❌ | ❌ | ✅ |
| `r02_refinement_in_non_view_file` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `r03_two_models_refine_one_view_differently` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `r04_later_include_wins` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `r05_last_refinement_in_file_wins` | confirmed | ✅ | ❌ | ❌ | ✅ |
| `r06_refinement_included_before_its_base` | provisional | ✅ | ❌ | ❌ | ✅ |
| `r07_field_refinement_keeps_unset_parameters` | confirmed | ✅ | ❌ | ✅ | ❌ |
| `r08_refinement_adds_fields` | confirmed | ✅ | ❌ | ✅ | ✅ |
| `r09_field_filters_are_additive` | confirmed | ❌ | N/A | N/A | ❌ |
| `r10_final_refinement_blocks_later_ones` | provisional | ❌ | ❌ | ❌ | ❌ |
| `r11_derived_table_refined_parameter_by_parameter` | confirmed | ✅ | N/A | N/A | ✅ |
| `r12_refinement_without_a_base_view` | provisional | ✅ | ❌ | ✅ | ✅ |
| `r13_dimension_group_timeframes_override` | confirmed | ✅ | N/A | N/A | ❌ |
| `r14_refinement_in_the_model_file` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `i01_wildcard_include_applies_in_path_order` | provisional | ✅ | ❌ | ❌ | ✅ |
| `i02_nested_include_expands_in_place` | provisional | ❌ | ❌ | ❌ | ❌ |
| `i03_file_included_twice_keeps_first_position` | provisional | ✅ | ❌ | ❌ | ❌ |
| `i04_relative_include_resolves_from_the_including_file` | confirmed | ✅ | ❌ | ❌ | ✅ |
| `i05_project_wildcards_do_not_reach_imported_projects` | confirmed | ❌ | ✅ | ✅ | ❌ |
| `i06_imported_project_view_can_be_refined` | confirmed | ✅ | ❌ | ❌ | ✅ |
| `i07_absolute_include_inside_an_imported_project` | confirmed | ✅ | ❌ | ✅ | ❌ |
| `i08_include_cycle_terminates` | provisional | ✅ | ❌ | ❌ | ✅ |
| `i09_dashboard_files_are_not_views` | confirmed | ✅ | ✅ | ✅ | ✅ |
| `e01_extends_inherits_the_refined_base` | provisional | ✅ | ❌ | ❌ | ✅ |
| `e02_extends_is_additive_under_refinement` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `e03_multiple_extends_last_listed_wins` | confirmed | ✅ | ❌ | ❌ | ✅ |
| `e04_child_overrides_extended_bases` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `m01_model_without_the_refinement_sees_the_base` | confirmed | ✅ | ❌ | ❌ | ❌ |
| `x01_explore_view_name_binds_base_view` | confirmed | ✅ | N/A | N/A | ✅ |
| `x02_explore_from_and_join_from_bind_views` | confirmed | ✅ | N/A | N/A | ✅ |
| `c01_manifest_constant_in_sql_table_name` | confirmed | ❌ | ✅ | ✅ | ❌ |
| `c02_manifest_constant_in_derived_table_sql` | confirmed | ❌ | ✅ | ✅ | ❌ |
| `l01_derived_table_reads_view_table` | confirmed | N/A | ❌ | ✅ | ✅ |
| `l02_chained_derived_tables_reach_the_base_table` | confirmed | N/A | ❌ | ✅ | ✅ |
| `l03_derived_table_reads_a_table_and_a_view` | confirmed | N/A | ❌ | ✅ | ❌ |
| `l04_reference_follows_the_refined_table` | confirmed | N/A | ❌ | ❌ | ✅ |
| `l05_native_derived_table_reads_its_explore` | confirmed | N/A | ❌ | ✅ | ❌ |
| `p01_single_semicolon_inside_sql_block` | confirmed | ❌ | ✅ | ✅ | ✅ |
| `p02_hash_inside_sql_block_is_not_lookml_comment` | confirmed | ✅ | ✅ | ✅ | ✅ |
| `p03_named_fields_errors_and_info` | confirmed | ❌ | ✅ | ✅ | ✅ |

## Failure details

- `r01_refinement_overrides_sql_table_name` · **OpenMetadata**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; ecommerce.orders.fields: expected ['id', 'status'], got ['id']; views that must not exist were exposed: ['+orders']
- `r01_refinement_overrides_sql_table_name` · **DataHub**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'
- `r02_refinement_in_non_view_file` · **OpenMetadata**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'
- `r02_refinement_in_non_view_file` · **DataHub**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'
- `r02_refinement_in_non_view_file` · **Dagster**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'
- `r03_two_models_refine_one_view_differently` · **OpenMetadata**: main.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; sandbox.orders.sql_table_name: expected 'sandbox.orders_test', got 'raw.orders'; views that must not exist were exposed: ['+orders']
- `r03_two_models_refine_one_view_differently` · **DataHub**: main.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; sandbox.orders.sql_table_name: expected 'sandbox.orders_test', got 'raw.orders'
- `r03_two_models_refine_one_view_differently` · **Dagster**: main.orders.sql_table_name: expected 'analytics.orders_clean', got 'sandbox.orders_test'
- `r04_later_include_wins` · **OpenMetadata**: m.orders.sql_table_name: expected 'from_a', got 'raw.orders'
- `r04_later_include_wins` · **DataHub**: m.orders.sql_table_name: expected 'from_a', got 'raw.orders'
- `r04_later_include_wins` · **Dagster**: as written: m.orders.sql_table_name: expected 'from_a', got 'from_b'; a.view.lkml and b.view.lkml exchanged: pass
- `r05_last_refinement_in_file_wins` · **OpenMetadata**: m.orders.sql_table_name: expected 'second', got 'raw.orders'
- `r05_last_refinement_in_file_wins` · **DataHub**: m.orders.sql_table_name: expected 'second', got 'raw.orders'
- `r06_refinement_included_before_its_base` · **OpenMetadata**: m.orders.sql_table_name: expected 'refined', got 'raw.orders'
- `r06_refinement_included_before_its_base` · **DataHub**: m.orders.sql_table_name: expected 'refined', got 'raw.orders'
- `r07_field_refinement_keeps_unset_parameters` · **OpenMetadata**: m.orders.id.label: expected 'Order ID', got 'Id'
- `r07_field_refinement_keeps_unset_parameters` · **Dagster**: m.orders.id.sql: expected '${TABLE}.id', got None; m.orders.id.type: expected 'number', got None
- `r08_refinement_adds_fields` · **OpenMetadata**: m.orders.fields: expected ['created', 'id', 'n', 'status'], got ['id', 'n']
- `r09_field_filters_are_additive` · **node-lookml-parser**: m.orders.n.filters: expected [{'status': 'complete'}, {'region': 'EU'}], got [{'region': 'EU'}]
- `r09_field_filters_are_additive` · **Dagster**: m.orders.n.filters: expected [{'status': 'complete'}, {'region': 'EU'}], got [{'region': 'EU'}]
- `r10_final_refinement_blocks_later_ones` · **node-lookml-parser**: m.orders.sql_table_name: expected 'a.final', got 'b.later'
- `r10_final_refinement_blocks_later_ones` · **OpenMetadata**: m.orders.sql_table_name: expected 'a.final', got 'raw.orders'
- `r10_final_refinement_blocks_later_ones` · **DataHub**: m.orders.sql_table_name: expected 'a.final', got 'raw.orders'
- `r10_final_refinement_blocks_later_ones` · **Dagster**: as written: pass; r_final.view.lkml and r_later.view.lkml exchanged: m.orders.sql_table_name: expected 'a.final', got 'b.later'
- `r12_refinement_without_a_base_view` · **OpenMetadata**: views that must not exist were exposed: ['+ghost']
- `r13_dimension_group_timeframes_override` · **Dagster**: m.orders.created.type: expected 'time', got None; m.orders.created.sql: expected '${TABLE}.created_at', got None
- `r14_refinement_in_the_model_file` · **OpenMetadata**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; ecommerce.orders.fields: expected ['id', 'status'], got ['id']
- `r14_refinement_in_the_model_file` · **DataHub**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; ecommerce.orders.fields: expected ['id', 'status'], got ['id']
- `r14_refinement_in_the_model_file` · **Dagster**: ecommerce.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; ecommerce.orders.fields: expected ['id', 'status'], got ['id']
- `i01_wildcard_include_applies_in_path_order` · **OpenMetadata**: m.orders.sql_table_name: expected 'from_b', got 'raw.orders'
- `i01_wildcard_include_applies_in_path_order` · **DataHub**: m.orders.sql_table_name: expected 'from_b', got 'raw.orders'
- `i02_nested_include_expands_in_place` · **node-lookml-parser**: m1.orders.sql_table_name: expected 'a', got 'b'
- `i02_nested_include_expands_in_place` · **OpenMetadata**: m1.orders.sql_table_name: expected 'a', got 'raw.orders'; m2.orders.sql_table_name: expected 'c', got 'raw.orders'
- `i02_nested_include_expands_in_place` · **DataHub**: m1.orders.sql_table_name: expected 'a', got 'raw.orders'; m2.orders.sql_table_name: expected 'c', got 'raw.orders'
- `i02_nested_include_expands_in_place` · **Dagster**: as written: m1.orders.sql_table_name: expected 'a', got 'b'; as written: m2.orders.sql_table_name: expected 'c', got 'b'; ra.view.lkml and rb.view.lkml exchanged: m2.orders.sql_table_name: expected 'c', got 'a'; rb.view.lkml and rc.view.lkml exchanged: m1.orders.sql_table_name: expected 'a', got 'c'
- `i03_file_included_twice_keeps_first_position` · **OpenMetadata**: m.orders.sql_table_name: expected 'a', got 'raw.orders'
- `i03_file_included_twice_keeps_first_position` · **DataHub**: m.orders.sql_table_name: expected 'a', got 'raw.orders'
- `i03_file_included_twice_keeps_first_position` · **Dagster**: as written: m.orders.sql_table_name: expected 'a', got 'b'; ra.view.lkml and rb.view.lkml exchanged: pass
- `i04_relative_include_resolves_from_the_including_file` · **OpenMetadata**: m.orders.sql_table_name: expected 'rel', got 'raw.orders'
- `i04_relative_include_resolves_from_the_including_file` · **DataHub**: m.orders.sql_table_name: expected 'rel', got 'raw.orders'
- `i05_project_wildcards_do_not_reach_imported_projects` · **node-lookml-parser**: m.orders.sql_table_name: expected 'raw.orders', got 'imported'
- `i05_project_wildcards_do_not_reach_imported_projects` · **Dagster**: m.orders.sql_table_name: expected 'raw.orders', got 'imported'
- `i06_imported_project_view_can_be_refined` · **OpenMetadata**: m.orders.sql_table_name: expected 'local.orders', got 'raw.orders'
- `i06_imported_project_view_can_be_refined` · **DataHub**: m.orders.sql_table_name: expected 'local.orders', got 'raw.orders'
- `i07_absolute_include_inside_an_imported_project` · **OpenMetadata**: m.orders.sql_table_name: expected 'shared.orders', got 'raw.orders'
- `i07_absolute_include_inside_an_imported_project` · **Dagster**: m.orders.sql_table_name: expected 'shared.orders', got 'raw.orders'
- `i08_include_cycle_terminates` · **OpenMetadata**: m.orders.sql_table_name: expected 'b', got 'raw.orders'
- `i08_include_cycle_terminates` · **DataHub**: m.orders.sql_table_name: expected 'b', got 'raw.orders'
- `e01_extends_inherits_the_refined_base` · **OpenMetadata**: main.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; main.orders_ext.sql_table_name: expected 'analytics.orders_clean', got None; main.orders_ext.fields: expected ['extra', 'id'], got ['extra']
- `e01_extends_inherits_the_refined_base` · **DataHub**: main.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; main.orders_ext.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'
- `e02_extends_is_additive_under_refinement` · **OpenMetadata**: m.orders.sql_table_name: expected 'b.t', got None; m.orders.fields: expected ['a_field', 'b_field', 'id'], got ['id']
- `e02_extends_is_additive_under_refinement` · **DataHub**: m.orders.sql_table_name: expected 'b.t', got 'a.t'; m.orders.fields: expected ['a_field', 'b_field', 'id'], got ['a_field', 'id']
- `e02_extends_is_additive_under_refinement` · **Dagster**: m.orders.sql_table_name: expected 'b.t', got 'a.t'; m.orders.fields: expected ['a_field', 'b_field', 'id'], got ['a_field', 'id']
- `e03_multiple_extends_last_listed_wins` · **OpenMetadata**: m.combined.sql_table_name: expected 'b.t', got None; m.combined.fields: expected ['a_field', 'b_field', 'own', 'shared'], got ['own']; m.combined.shared: field not resolved
- `e03_multiple_extends_last_listed_wins` · **DataHub**: m.combined.fields: expected ['a_field', 'b_field', 'own', 'shared'], got ['b_field', 'own', 'shared']
- `e04_child_overrides_extended_bases` · **OpenMetadata**: m.child.fields: expected ['a_only', 'id'], got ['id']; m.child.id.sql: expected '${TABLE}.b_id', got None
- `e04_child_overrides_extended_bases` · **DataHub**: m.child.fields: expected ['a_only', 'id'], got ['id']; m.child.id.sql: expected '${TABLE}.b_id', got None
- `e04_child_overrides_extended_bases` · **Dagster**: m.child.id.sql: expected '${TABLE}.b_id', got None
- `m01_model_without_the_refinement_sees_the_base` · **OpenMetadata**: refined.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'; views that must not exist were exposed: ['+orders']
- `m01_model_without_the_refinement_sees_the_base` · **DataHub**: refined.orders.sql_table_name: expected 'analytics.orders_clean', got 'raw.orders'
- `m01_model_without_the_refinement_sees_the_base` · **Dagster**: plain.orders.sql_table_name: expected 'raw.orders', got 'analytics.orders_clean'
- `c01_manifest_constant_in_sql_table_name` · **node-lookml-parser**: m.orders.sql_table_name: expected 'analytics_prod.orders', got '@{ANALYTICS_SCHEMA}.orders'
- `c01_manifest_constant_in_sql_table_name` · **Dagster**: m.orders.sql_table_name: expected 'analytics_prod.orders', got '@{ANALYTICS_SCHEMA}.orders'
- `c02_manifest_constant_in_derived_table_sql` · **node-lookml-parser**: m.orders.derived_table.sql: expected 'SELECT id FROM `bq_project.raw.orders`', got 'SELECT id FROM `@{RAW_DATASET}.orders`'
- `c02_manifest_constant_in_derived_table_sql` · **Dagster**: m.orders.derived_table.sql: expected 'SELECT id FROM `bq_project.raw.orders`', got 'SELECT id FROM `@{RAW_DATASET}.orders`'
- `l01_derived_table_reads_view_table` · **OpenMetadata**: as written: m.order_facts.upstream_tables: expected ['raw.orders'], got []; reported upstream: []; views/order_facts.view.lkml and views/orders.view.lkml exchanged: pass
- `l02_chained_derived_tables_reach_the_base_table` · **OpenMetadata**: m.orders_rollup_repeat.upstream_tables: expected ['raw.orders'], got []; reported upstream: []
- `l03_derived_table_reads_a_table_and_a_view` · **OpenMetadata**: as written: m.orders_by_customer.upstream_tables: expected ['raw.customers', 'raw.orders'], got []; reported upstream: []; views/orders.view.lkml and views/orders_by_customer.view.lkml exchanged: pass
- `l03_derived_table_reads_a_table_and_a_view` · **Dagster**: m.orders_by_customer.upstream_tables: expected ['raw.customers', 'raw.orders'], got ['raw.orders']; reported upstream: ['view orders']
- `l04_reference_follows_the_refined_table` · **OpenMetadata**: as written: m.orders_rollup.upstream_tables: expected ['analytics.orders_clean'], got ['raw.orders']; reported upstream: ['table raw.orders']; views/orders.view.lkml and views/orders_rollup.view.lkml exchanged: m.orders_rollup.upstream_tables: expected ['analytics.orders_clean'], got []; reported upstream: []; views/orders_refinements.view.lkml and views/orders_rollup.view.lkml exchanged: m.orders_rollup.upstream_tables: expected ['analytics.orders_clean'], got ['raw.orders']; reported upstream: ['table raw.orders']
- `l04_reference_follows_the_refined_table` · **DataHub**: m.orders_rollup.upstream_tables: expected ['analytics.orders_clean'], got ['raw.orders']; reported upstream: ['view orders']
- `l05_native_derived_table_reads_its_explore` · **OpenMetadata**: m.orders_by_country.upstream_tables: expected ['raw.orders', 'raw.users'], got []; reported upstream: []
- `l05_native_derived_table_reads_its_explore` · **Dagster**: m.orders_by_country.upstream_tables: expected ['raw.orders', 'raw.users'], got ['orders_by_country']; reported upstream: ['table orders_by_country']
- `p01_single_semicolon_inside_sql_block` · **node-lookml-parser**: m.orders.derived_table.sql: expected "SELECT id FROM raw.orders WHERE note != ';'", got "SELECT id FROM raw.orders WHERE note != ';,'"; m.orders.cleaned.sql: expected "REGEXP_REPLACE(${TABLE}.note, ';', '')", got "REGEXP_REPLACE(${TABLE}.note, ';,', '')"
- `p03_named_fields_errors_and_info` · **node-lookml-parser**: m.orders.info.type: expected 'string', got None; m.orders.info.sql: expected '${TABLE}.info', got None; m.orders.errors.type: expected 'count', got None
