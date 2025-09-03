// Pretty print a method list + docs for a chosen region type
import {REGION_CATALOG} from "@/modules/catalog.jsx";
import {Card, CardContent, CardHeader, CardTitle} from "@/components/ui/card.jsx";

export function MethodList({ typeName }) {
    const methods = REGION_CATALOG[typeName].methods;
    const entries = Object.entries(methods);
    return (
        <div className="space-y-2">
            {entries.map(([name, m]) => (
                <Card key={name} className="border rounded-md">
                    <CardHeader className="py-0">
                        <CardTitle className="text-sm font-semibold">{name}()</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0 pb-0">
                        <div className="text-xs text-gray-600 whitespace-pre-wrap">{m.doc}</div>
                    </CardContent>
                </Card>
            ))}
            {entries.length === 0 && <div className="text-xs text-gray-500">No methods documented for this type.</div>}
        </div>
    );
}
