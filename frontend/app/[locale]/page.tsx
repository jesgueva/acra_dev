import { redirect } from "next/navigation";
import { getLocale } from "next-intl/server";

export default async function LocaleHomePage() {
  const locale = await getLocale();
  // Dashboard rather than /receiving — see the note in AuthForm: it is the only module every role
  // is allowed to see, so it is the one safe landing page.
  redirect(`/${locale}/dashboard`);
}
