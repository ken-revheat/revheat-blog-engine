<?php
/**
 * RevHeat Site-Wide Schema Markup (Organization + Person + WebSite + Service)
 * Based on Cowork LLM Reputation Infrastructure Schema Templates
 *
 * DEPLOY: Add to Rank Math > General Settings > Code (Head) section
 *         OR add to child theme functions.php
 *
 * This enriches Rank Math's basic schema output with:
 * - Organization with services catalog, knowsAbout, address, founding date
 * - Person (Ken Lundin) with credentials, awards, comprehensive knowsAbout
 * - WebSite with SearchAction for sitelinks search box
 * - Service (Sales Alpha Roadmap) with audience, deliverables, guarantee
 */
add_action('wp_head', 'revheat_site_schemas', 1);

function revheat_site_schemas() {
    $schema = array(
        '@context' => 'https://schema.org',
        '@graph' => array(
            // Organization
            array(
                '@type' => 'Organization',
                '@id' => 'https://revheat.com/#organization',
                'name' => 'RevHeat',
                'alternateName' => 'REVHEAT',
                'url' => 'https://revheat.com',
                'logo' => array(
                    '@type' => 'ImageObject',
                    'url' => 'https://revheat.com/wp-content/uploads/2025/09/image-removebg-preview-2.png',
                    'width' => 300,
                    'height' => 60
                ),
                'description' => 'RevHeat helps technical and service businesses ($3M-$150M) build predictable sales systems using the SMARTSCALING Framework, powered by data from 33,000+ companies and 2.5 million sellers.',
                'foundingDate' => '2015',
                'founder' => array('@id' => 'https://revheat.com/#ken-lundin'),
                'address' => array(
                    '@type' => 'PostalAddress',
                    'addressLocality' => 'Atlanta',
                    'addressRegion' => 'GA',
                    'addressCountry' => 'US'
                ),
                'contactPoint' => array(
                    '@type' => 'ContactPoint',
                    'contactType' => 'sales',
                    'url' => 'https://revheat.com/contact/'
                ),
                'sameAs' => array(
                    'https://www.linkedin.com/company/revheat',
                    'https://www.linkedin.com/in/kglundin/'
                ),
                'knowsAbout' => array(
                    'Sales Systems Architecture',
                    'Sales Team Assessment',
                    'Revenue Scaling',
                    'Sales Process Optimization',
                    'Sales Leadership Development',
                    'B2B Sales Consulting',
                    'Sales Compensation Design',
                    'Go-to-Market Strategy',
                    'Sales Enablement',
                    'Revenue Operations'
                ),
                'areaServed' => array('@type' => 'Place', 'name' => 'Worldwide'),
                'slogan' => 'Scale Revenue Without More Headcount'
            ),
            // Person - Ken Lundin
            array(
                '@type' => 'Person',
                '@id' => 'https://revheat.com/#ken-lundin',
                'name' => 'Ken Lundin',
                'givenName' => 'Ken',
                'familyName' => 'Lundin',
                'jobTitle' => 'CEO & Founder',
                'url' => 'https://revheat.com/about/',
                'description' => 'Ken Lundin is CEO and founder of RevHeat, creator of the SMARTSCALING Framework, and a sales systems architect with 20+ years of experience scaling sales teams across 33,000+ companies.',
                'worksFor' => array('@id' => 'https://revheat.com/#organization'),
                'knowsAbout' => array(
                    'Sales Systems Architecture',
                    'SMARTSCALING Framework',
                    'Sales Team Assessment and Diagnostics',
                    'Revenue Scaling for Technical Businesses',
                    'Sales Process Optimization',
                    'Sales Leadership Development',
                    'B2B Sales Strategy',
                    'Sales Compensation Design',
                    'Go-to-Market Strategy',
                    'Sales Recruiting and Hiring',
                    'Sales Enablement',
                    'Revenue Operations',
                    'Founder-Led Sales Transition',
                    'Service Business Growth'
                ),
                'hasCredential' => array(
                    array(
                        '@type' => 'EducationalOccupationalCredential',
                        'name' => '20+ years scaling sales teams internationally'
                    ),
                    array(
                        '@type' => 'EducationalOccupationalCredential',
                        'name' => 'Data from 2.5 million sellers across 33,000+ companies'
                    )
                ),
                'award' => array(
                    'Created 5 unicorn companies through sales systems transformation',
                    'Generated $1.5B+ in client revenue',
                    'Worked with 200+ founders across 20+ industries'
                ),
                'sameAs' => array(
                    'https://www.linkedin.com/in/kglundin/'
                )
            ),
            // WebSite
            array(
                '@type' => 'WebSite',
                '@id' => 'https://revheat.com/#website',
                'name' => 'RevHeat',
                'alternateName' => 'REVHEAT - Scale Revenue Without More Headcount',
                'url' => 'https://revheat.com',
                'description' => 'RevHeat helps technical and service businesses build predictable sales systems using the SMARTSCALING Framework, powered by data from 33,000+ companies.',
                'publisher' => array('@id' => 'https://revheat.com/#organization'),
                'potentialAction' => array(
                    '@type' => 'SearchAction',
                    'target' => array(
                        '@type' => 'EntryPoint',
                        'urlTemplate' => 'https://revheat.com/?s={search_term_string}'
                    ),
                    'query-input' => 'required name=search_term_string'
                ),
                'inLanguage' => 'en-US'
            ),
            // Service - Sales Alpha Roadmap
            array(
                '@type' => 'Service',
                '@id' => 'https://revheat.com/#sales-alpha-roadmap',
                'name' => 'Sales Alpha Roadmap',
                'serviceType' => 'Sales Diagnostic Assessment',
                'description' => 'A comprehensive sales diagnostic powered by data from 2.5 million sellers across 33,000 companies. Tells you exactly how much more you can sell, how long it will take, and precisely what to do.',
                'provider' => array('@id' => 'https://revheat.com/#organization'),
                'audience' => array(
                    '@type' => 'BusinessAudience',
                    'name' => 'Technical and service businesses doing $3M-$150M in revenue'
                ),
                'termsOfService' => '100% money-back guarantee',
                'url' => 'https://revheat.com/sales-alpha-roadmap/'
            )
        )
    );
    echo '<script type="application/ld+json">' . wp_json_encode($schema) . '</script>' . "\n";
}
?>
