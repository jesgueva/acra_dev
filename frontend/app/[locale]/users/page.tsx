import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import { Users } from "@/src/components/users/Users";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function UsersPage() {
  return (
    <PrivilegeGate privilege={PRIVILEGES.USERS_MANAGE}>
      <Users />
    </PrivilegeGate>
  );
}
