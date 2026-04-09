import { getTranslations } from "next-intl/server";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default async function UsersPage() {
  const t = await getTranslations("users");

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <Card className="max-w-3xl">
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            User management will appear here.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
