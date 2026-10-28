import React from "react";
import AdminWageSettings from "./AdminWageSettings";

/**
 * Backward-compatibility wrapper for /admin/delivery-wage-settings.
 * Renders AdminWageSettings directly focused on the delivery tab.
 */
export default function AdminDeliveryWageSettings(props) {
  return <AdminWageSettings defaultTab="delivery" {...props} />;
}
