from django.db import migrations

def seed_stories(apps, schema_editor):
    Story = apps.get_model("main", "Story")
    if Story.objects.count() == 0:
        Story.objects.create(
            title="Sandro Dias breaks two world records on the biggest skate ramp ever",
            category="SKATEBOARDING",
            read_time="6 min read",
            excerpt="Skateboarding history made: Sandro Dias drops in from a 22 storey building and shatters the high-speed ramp barrier.",
            content="Brazilian skateboarding legend Sandro Dias etched his name into history by conquering the world's most daunting mega ramp, establishing new world records for vertical drop-in height and top speed on four wheels.",
            image_data_url="https://images.unsplash.com/photo-1520045884218-a66e955d041c?auto=format&fit=crop&w=800&q=80",
            order=1,
            is_active=True,
        )
        Story.objects.create(
            title="What is Red Bull 64 Bars?",
            category="MUSIC",
            read_time="2 min read",
            excerpt="A quick and simple explanation to the concept of a unique global project that is challenging rap artists around the globe.",
            content="Red Bull 64 Bars is an unadulterated freestyle cipher format: no chorus, no hooks, no distractions — just straight raw lyrical talent over hard-hitting production.",
            image_data_url="https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?auto=format&fit=crop&w=800&q=80",
            order=2,
            is_active=True,
        )
        Story.objects.create(
            title="Back with a bang: B-Girl Bar-B's road to Red Bull BC One World Final Tokyo",
            category="BREAKING",
            read_time="5 min read",
            excerpt="After two years of near misses, Bar-B stormed back to claim the Red Bull BC One Cypher India championship.",
            content="With electrifying footwork and gravity-defying freezes, B-Girl Bar-B took the national breaking scene by storm on her way to representing on the global stage in Tokyo.",
            image_data_url="https://images.unsplash.com/photo-1508700115892-45ecd05ae2ad?auto=format&fit=crop&w=800&q=80",
            order=3,
            is_active=True,
        )
        Story.objects.create(
            title="Lyrics to '43 Ki Hawa' by Vijay DK x Karan Kanchan",
            category="MUSIC",
            read_time="3 min read",
            excerpt="Lyrics and exclusive track breakdown of the high-octane collaboration from season 3 of Red Bull 64 Bars India.",
            content="A bar-for-bar breakdown of the cultural punchlines and street metaphors driving the explosive sonic explosion created by Vijay DK and Karan Kanchan.",
            image_data_url="https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=800&q=80",
            order=4,
            is_active=True,
        )

def unseed_stories(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('main', '0042_story_alter_sitedetails_homepage_video_id'),
    ]

    operations = [
        migrations.RunPython(seed_stories, unseed_stories),
    ]
