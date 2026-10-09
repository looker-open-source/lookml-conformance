include: "/orders.view"
view: +orders {
  derived_table: {
    datagroup_trigger: daily
  }
}
