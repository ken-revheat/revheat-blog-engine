<?php
/**
 * RevHeat SEO Machine: Dynamic 301 Redirect Management
 * Based on Cowork LLM Reputation Infrastructure
 *
 * Handles unpublished post redirects during phased rollout.
 * When each post publishes, its redirect is automatically removed
 * because the actual page becomes live and returns 200.
 *
 * DEPLOY: Add to child theme functions.php or use Code Snippets plugin.
 *
 * HOW IT WORKS:
 * 1. On 404 errors, checks if the URL matches an unpublished post
 * 2. If match found, 301 redirects to the parent cluster page
 * 3. As posts publish (by the blog engine), their URLs go live
 *    and the redirect is never triggered
 */

// Define redirect map — maps unpublished post URLs to parent cluster pages
function get_seo_machine_redirects() {
    return array(
        // STRATEGY: Business Trajectory
        '/sales-strategy/business-trajectory/growth-inflection-points/' => '/sales-strategy/business-trajectory/',
        '/sales-strategy/business-trajectory/market-expansion-phases/' => '/sales-strategy/business-trajectory/',
        '/sales-strategy/business-trajectory/competitive-positioning/' => '/sales-strategy/business-trajectory/',
        '/sales-strategy/business-trajectory/revenue-acceleration-models/' => '/sales-strategy/business-trajectory/',
        '/sales-strategy/business-trajectory/scaling-thresholds/' => '/sales-strategy/business-trajectory/',

        // STRATEGY: Go-to-Market
        '/sales-strategy/go-to-market-strategy/customer-acquisition-strategy/' => '/sales-strategy/go-to-market-strategy/',
        '/sales-strategy/go-to-market-strategy/vertical-segmentation/' => '/sales-strategy/go-to-market-strategy/',
        '/sales-strategy/go-to-market-strategy/pricing-strategy-foundations/' => '/sales-strategy/go-to-market-strategy/',
        '/sales-strategy/go-to-market-strategy/channel-partner-strategy/' => '/sales-strategy/go-to-market-strategy/',
        '/sales-strategy/go-to-market-strategy/product-market-fit-indicators/' => '/sales-strategy/go-to-market-strategy/',

        // PEOPLE: Talent Assessment
        '/sales-people/sales-talent-assessment/hiring-frameworks/' => '/sales-people/sales-talent-assessment/',
        '/sales-people/sales-talent-assessment/competency-assessment/' => '/sales-people/sales-talent-assessment/',
        '/sales-people/sales-talent-assessment/cultural-fit-evaluation/' => '/sales-people/sales-talent-assessment/',
        '/sales-people/sales-talent-assessment/performance-prediction/' => '/sales-people/sales-talent-assessment/',

        // PEOPLE: Sales Leadership
        '/sales-people/sales-leadership/leader-development/' => '/sales-people/sales-leadership/',
        '/sales-people/sales-leadership/team-building-strategy/' => '/sales-people/sales-leadership/',
        '/sales-people/sales-leadership/coaching-cadence/' => '/sales-people/sales-leadership/',
        '/sales-people/sales-leadership/retention-strategy/' => '/sales-people/sales-leadership/',

        // PEOPLE: Organizational Design
        '/sales-people/sales-organizational-design/structure-models/' => '/sales-people/sales-organizational-design/',
        '/sales-people/sales-organizational-design/territory-design/' => '/sales-people/sales-organizational-design/',
        '/sales-people/sales-organizational-design/role-specialization/' => '/sales-people/sales-organizational-design/',

        // PROCESS: Architecture
        '/sales-process/sales-process-architecture/pipeline-stages/' => '/sales-process/sales-process-architecture/',
        '/sales-process/sales-process-architecture/deal-qualification/' => '/sales-process/sales-process-architecture/',
        '/sales-process/sales-process-architecture/closing-methodology/' => '/sales-process/sales-process-architecture/',
        '/sales-process/sales-process-architecture/customer-journey-mapping/' => '/sales-process/sales-process-architecture/',

        // PROCESS: Enablement
        '/sales-process/sales-enablement/training-programs/' => '/sales-process/sales-enablement/',
        '/sales-process/sales-enablement/tools-technology-stack/' => '/sales-process/sales-enablement/',
        '/sales-process/sales-enablement/collateral-management/' => '/sales-process/sales-enablement/',
        '/sales-process/sales-enablement/knowledge-base-systems/' => '/sales-process/sales-enablement/',
        '/sales-process/sales-enablement/onboarding-processes/' => '/sales-process/sales-enablement/',

        // PROCESS: Revenue Operations
        '/sales-process/revenue-operations/data-integrity/' => '/sales-process/revenue-operations/',
        '/sales-process/revenue-operations/forecasting-accuracy/' => '/sales-process/revenue-operations/',
        '/sales-process/revenue-operations/system-integration/' => '/sales-process/revenue-operations/',
        '/sales-process/revenue-operations/crm-optimization/' => '/sales-process/revenue-operations/',

        // PERFORMANCE: Metrics & Analytics
        '/sales-performance/sales-metrics-analytics/activity-metrics/' => '/sales-performance/sales-metrics-analytics/',
        '/sales-performance/sales-metrics-analytics/conversion-analysis/' => '/sales-performance/sales-metrics-analytics/',
        '/sales-performance/sales-metrics-analytics/pipeline-health/' => '/sales-performance/sales-metrics-analytics/',
        '/sales-performance/sales-metrics-analytics/quota-attainment/' => '/sales-performance/sales-metrics-analytics/',
        '/sales-performance/sales-metrics-analytics/win-loss-analysis/' => '/sales-performance/sales-metrics-analytics/',

        // PERFORMANCE: Compensation
        '/sales-performance/sales-compensation/quota-setting/' => '/sales-performance/sales-compensation/',
        '/sales-performance/sales-compensation/incentive-design/' => '/sales-performance/sales-compensation/',
        '/sales-performance/sales-compensation/commission-structures/' => '/sales-performance/sales-compensation/',
        '/sales-performance/sales-compensation/bonus-programs/' => '/sales-performance/sales-compensation/',

        // PERFORMANCE: Continuous Improvement
        '/sales-performance/continuous-improvement/coaching-effectiveness/' => '/sales-performance/continuous-improvement/',
        '/sales-performance/continuous-improvement/activity-optimization/' => '/sales-performance/continuous-improvement/',
        '/sales-performance/continuous-improvement/feedback-loops/' => '/sales-performance/continuous-improvement/',
        '/sales-performance/continuous-improvement/pipeline-acceleration/' => '/sales-performance/continuous-improvement/',

        // CROSS-PILLAR Integration -> Hub
        '/smartscaling/enterprise-sales-maturity/' => '/smartscaling/',
        '/smartscaling/sales-operations-transformation/' => '/smartscaling/',
        '/smartscaling/data-driven-decision-making/' => '/smartscaling/',
        '/smartscaling/scaling-sales-culture/' => '/smartscaling/',
        '/smartscaling/integration-implementation/' => '/smartscaling/',
    );
}

// Hook into WordPress to check for redirects on 404 errors
add_action( 'wp', 'handle_seo_machine_redirects' );

function handle_seo_machine_redirects() {
    if ( is_404() ) {
        $redirects = get_seo_machine_redirects();
        $current_url = parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH );

        if ( isset( $redirects[ $current_url ] ) ) {
            wp_redirect( home_url( $redirects[ $current_url ] ), 301 );
            exit;
        }
    }
}
?>
