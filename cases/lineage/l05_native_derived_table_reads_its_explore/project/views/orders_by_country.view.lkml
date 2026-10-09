view: orders_by_country {
  derived_table: {
    explore_source: orders {
      column: country { field: users.country }
      column: order_count { field: orders.count }
    }
  }
  dimension: country {}
  dimension: order_count { type: number }
}
