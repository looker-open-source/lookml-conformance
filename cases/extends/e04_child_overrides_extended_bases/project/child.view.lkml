include: "/bases.view"
view: child {
  extends: [base_a, base_b]
  sql_table_name: child.t ;;
  dimension: id { label: "Child ID" }
}
