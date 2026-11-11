import "./access-switch-control.css";

export function AccessSwitchControl({
  id, checked, disabled, label, onChange,
}: {
  id?: string;
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}) {
  return <button
    id={id}
    className={checked ? "access-management__switch access-management__switch--on" : "access-management__switch"}
    type="button" role="switch" aria-checked={checked} aria-label={label}
    disabled={disabled} onClick={onChange}
  ><span /></button>;
}
