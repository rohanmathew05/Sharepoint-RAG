import { DEMO_USERS } from "../types";

export function UserSwitcher({
  currentUserId,
  onChange,
}: {
  currentUserId: string;
  onChange: (id: string) => void;
}) {
  const currentUser = DEMO_USERS.find((u) => u.id === currentUserId);
  return (
    <div className="user-switcher">
      <label htmlFor="demo-user-select">Signed in as</label>
      <select
        id="demo-user-select"
        value={currentUserId}
        onChange={(e) => onChange(e.target.value)}
      >
        {DEMO_USERS.map((u) => (
          <option key={u.id} value={u.id}>
            {u.label}
          </option>
        ))}
      </select>
      {currentUser && (
        <span className="user-groups">
          Access: {currentUser.groups.join(", ")}
        </span>
      )}
    </div>
  );
}
